// Minimal stand-in for the TrendSpider scripting runtime, so an indicator
// script can be run and checked under Node. It implements only the API the
// APEX script uses, following https://platform-docs.trendspider.com/scripting/docs/
// Indicator math (EMA/RSI/ATR/ADX) uses the standard Wilder/EMA definitions.

'use strict';

const isNumber = value => typeof value === 'number' && Number.isFinite(value);

function makeIndicatorMath(candleCount) {
	const seriesOf = value => new Array(candleCount).fill(value);

	function sma(series, length) {
		const result = new Array(series.length).fill(null);
		let windowSum = 0;
		let validInWindow = 0;
		for (let index = 0; index < series.length; index += 1) {
			const value = series[index];
			if (isNumber(value)) { windowSum += value; validInWindow += 1; }
			if (index >= length) {
				const dropped = series[index - length];
				if (isNumber(dropped)) { windowSum -= dropped; validInWindow -= 1; }
			}
			if (index >= length - 1 && validInWindow === length) {
				result[index] = windowSum / length;
			}
		}
		return result;
	}

	// EMA seeded with the SMA of the first `length` valid values.
	function ema(series, length) {
		const result = new Array(series.length).fill(null);
		const smoothing = 2 / (length + 1);
		let previous = null;
		let seed = [];
		for (let index = 0; index < series.length; index += 1) {
			const value = series[index];
			if (!isNumber(value)) { continue; }
			if (previous === null) {
				seed.push(value);
				if (seed.length === length) {
					previous = seed.reduce((a, b) => a + b, 0) / length;
					result[index] = previous;
				}
				continue;
			}
			previous = smoothing * value + (1 - smoothing) * previous;
			result[index] = previous;
		}
		return result;
	}

	// Wilder's moving average (RMA).
	function wildma(series, length) {
		const result = new Array(series.length).fill(null);
		let previous = null;
		let seed = [];
		for (let index = 0; index < series.length; index += 1) {
			const value = series[index];
			if (!isNumber(value)) { continue; }
			if (previous === null) {
				seed.push(value);
				if (seed.length === length) {
					previous = seed.reduce((a, b) => a + b, 0) / length;
					result[index] = previous;
				}
				continue;
			}
			previous = (previous * (length - 1) + value) / length;
			result[index] = previous;
		}
		return result;
	}

	function rsi(series, length) {
		const gains = series.map((value, index) => (index === 0 ? null : Math.max(value - series[index - 1], 0)));
		const losses = series.map((value, index) => (index === 0 ? null : Math.max(series[index - 1] - value, 0)));
		const averageGain = wildma(gains, length);
		const averageLoss = wildma(losses, length);
		return averageGain.map((gain, index) => {
			const loss = averageLoss[index];
			if (!isNumber(gain) || !isNumber(loss)) { return null; }
			if (loss === 0) { return 100; }
			return 100 - 100 / (1 + gain / loss);
		});
	}

	function trueRange(high, low, close) {
		return high.map((h, index) => (index === 0
			? h - low[index]
			: Math.max(h - low[index], Math.abs(h - close[index - 1]), Math.abs(low[index] - close[index - 1]))));
	}

	function adx(high, low, close, period) {
		const plusDm = high.map((h, index) => {
			if (index === 0) { return null; }
			const up = h - high[index - 1];
			const down = low[index - 1] - low[index];
			return up > down && up > 0 ? up : 0;
		});
		const minusDm = low.map((l, index) => {
			if (index === 0) { return null; }
			const up = high[index] - high[index - 1];
			const down = low[index - 1] - l;
			return down > up && down > 0 ? down : 0;
		});
		const tr = trueRange(high, low, close).map((value, index) => (index === 0 ? null : value));
		const smoothedTr = wildma(tr, period);
		const smoothedPlus = wildma(plusDm, period);
		const smoothedMinus = wildma(minusDm, period);
		const dmiPlus = smoothedPlus.map((value, index) => (isNumber(value) && smoothedTr[index] > 0 ? 100 * value / smoothedTr[index] : null));
		const dmiMinus = smoothedMinus.map((value, index) => (isNumber(value) && smoothedTr[index] > 0 ? 100 * value / smoothedTr[index] : null));
		const dx = dmiPlus.map((plus, index) => {
			const minus = dmiMinus[index];
			if (!isNumber(plus) || !isNumber(minus) || plus + minus === 0) { return null; }
			return 100 * Math.abs(plus - minus) / (plus + minus);
		});
		return { adx: wildma(dx, period), dmiPlus, dmiMinus };
	}

	return { seriesOf, sma, ema, wildma, rsi, trueRange, adx };
}

// Groups candles into a higher time frame. Each HTF candle is stamped with the
// time of its first candle (bar-start time, like TrendSpider's `time`).
function aggregateCandles(data, resolution, timeZone = 'America/New_York') {
	const keyFormatter = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' });
	const bucketKey = timestamp => {
		const parts = Object.fromEntries(keyFormatter.formatToParts(new Date(timestamp * 1000)).map(part => [part.type, part.value]));
		const day = `${parts.year}-${parts.month}-${parts.day}`;
		if (resolution === '60') { return `${day} ${parts.hour}`; }
		if (resolution === 'D') { return day; }
		if (resolution === 'M') { return `${parts.year}-${parts.month}`; }
		if (resolution === 'W') {
			const date = new Date(`${day}T00:00:00Z`);
			const mondayOffset = (date.getUTCDay() + 6) % 7;
			date.setUTCDate(date.getUTCDate() - mondayOffset);
			return date.toISOString().slice(0, 10);
		}
		throw new Error(`mock: unsupported resolution ${resolution}`);
	};

	const result = { time: [], open: [], high: [], low: [], close: [], volume: [] };
	let currentKey = null;
	for (let index = 0; index < data.time.length; index += 1) {
		const key = bucketKey(data.time[index]);
		if (key !== currentKey) {
			currentKey = key;
			result.time.push(data.time[index]);
			result.open.push(data.open[index]);
			result.high.push(data.high[index]);
			result.low.push(data.low[index]);
			result.close.push(data.close[index]);
			result.volume.push(data.volume[index]);
		}
		else {
			const last = result.time.length - 1;
			result.high[last] = Math.max(result.high[last], data.high[index]);
			result.low[last] = Math.min(result.low[last], data.low[index]);
			result.close[last] = data.close[index];
			result.volume[last] += data.volume[index];
		}
	}
	return result;
}

class ScriptError extends Error {}

// Runs an indicator script over `data` ({ time, open, high, low, close, volume })
// and returns everything it painted/registered.
async function runIndicator(source, data, options = {}) {
	const {
		ticker = 'TEST',
		resolution = 'D',
		inputOverrides = {},
		volumeDataAvailable = true,
		historyProvider = (requestedTicker, requestedResolution) => aggregateCandles(data, requestedResolution)
	} = options;

	const candleCount = data.close.length;
	const math = makeIndicatorMath(candleCount);
	const output = {
		description: null,
		inputs: [],
		paints: [],
		signals: [],
		clouds: [],
		candleColors: null,
		overlays: [],
		historyRequests: []
	};
	const usedNames = new Set();

	const claimName = (kind, name) => {
		if (!name) { throw new ScriptError(`${kind}: every output needs a fixed name`); }
		const key = `${kind}:${name}`;
		if (usedNames.has(key)) { throw new ScriptError(`${kind}: duplicate name "${name}"`); }
		usedNames.add(key);
	};

	const checkSeries = (kind, name, series) => {
		if (!Array.isArray(series) || series.length !== candleCount) {
			throw new ScriptError(`${kind} "${name}": expected ${candleCount} values, got ${series && series.length}`);
		}
	};

	function makeInputApi(prefix) {
		const declare = (kind, title, defaultValue, extra) => {
			output.inputs.push({ kind, title: `${prefix}${title}`, defaultValue, extra });
			const overridden = Object.prototype.hasOwnProperty.call(inputOverrides, title);
			const value = overridden ? inputOverrides[title] : defaultValue;
			if (kind === 'number' && extra && (isNumber(extra.min) && value < extra.min || isNumber(extra.max) && value > extra.max)) {
				throw new ScriptError(`input "${title}" out of range`);
			}
			if (kind === 'select' && !extra.includes(value)) {
				throw new ScriptError(`input "${title}": "${value}" is not one of the options`);
			}
			return value;
		};
		const api = (title, defaultValue = 0, extra) => declare('legacy', title, defaultValue, extra);
		api.number = (title, defaultValue = 0, extra) => declare('number', title, defaultValue, extra);
		api.text = (title, defaultValue = '', extra) => declare('text', title, defaultValue, extra);
		api.boolean = (title, defaultValue = true, extra) => declare('boolean', title, defaultValue, extra);
		api.select = (title, defaultValue, choices) => declare('select', title, defaultValue, choices);
		api.color = (title, defaultValue = 'black') => declare('color', title, defaultValue);
		api.tab = title => makeInputApi(`${title} / `);
		api.group = title => makeInputApi(`${prefix}${title} / `);
		api.row = () => makeInputApi(prefix);
		return api;
	}

	const prices = {
		time: data.time.slice(),
		open: data.open.slice(),
		high: data.high.slice(),
		low: data.low.slice(),
		close: data.close.slice(),
		volume: data.volume.slice()
	};
	prices.hl2 = prices.high.map((h, i) => (h + prices.low[i]) / 2);

	const api = {
		...prices,
		market: prices,
		current: { ticker, symbol: ticker, resolution, decimals: 2, volumeDataAvailable, now: prices.time[candleCount - 1] },
		constants: { time_frames: ['1', '5', '15', '30', '60', '240', 'D', 'W', 'M'], empty_series: math.seriesOf(null) },
		describe_indicator: (name, type = 'price', meta = {}) => { output.description = { name, type, meta }; },
		input: makeInputApi(''),
		assert: (condition, message) => { if (!condition) { throw new ScriptError(`assert: ${message}`); } },
		series_of: math.seriesOf,
		sma: math.sma,
		ema: math.ema,
		rsi: math.rsi,
		atr: length => math.wildma(math.trueRange(prices.high, prices.low, prices.close), length),
		indicators: { adx: (period = 14) => math.adx(prices.high, prices.low, prices.close, period) },
		for_every: (...args) => {
			const operation = args.pop();
			const result = new Array(candleCount).fill(null);
			let previous = null;
			for (let index = 0; index < candleCount; index += 1) {
				previous = operation(...args.map(series => series[index]), previous, index);
				result[index] = previous;
			}
			return result;
		},
		land_points_onto_series: (sourceTimes, sourceValues, targetTimes, method = 'eq') => {
			if (method !== 'ge') { throw new ScriptError('mock supports land_points_onto_series(..., "ge") only'); }
			const result = new Array(targetTimes.length).fill(null);
			let targetIndex = 0;
			for (let sourceIndex = 0; sourceIndex < sourceTimes.length; sourceIndex += 1) {
				while (targetIndex < targetTimes.length && targetTimes[targetIndex] < sourceTimes[sourceIndex]) { targetIndex += 1; }
				if (targetIndex < targetTimes.length) { result[targetIndex] = sourceValues[sourceIndex]; }
			}
			return result;
		},
		request: {
			history: async (requestedTicker, requestedResolution) => {
				output.historyRequests.push({ ticker: requestedTicker, resolution: requestedResolution });
				return historyProvider(requestedTicker, requestedResolution);
			}
		},
		paint: (series, params = {}) => {
			claimName('paint', params.name);
			checkSeries('paint', params.name, series);
			if (Array.isArray(params.color)) { checkSeries('paint color', params.name, params.color); }
			output.paints.push({ name: params.name, series, params });
			return { lineRef: params.name };
		},
		color_cloud: (series1, series2, color1, color2, name1, name2, opacity) => {
			claimName('cloud', name1);
			checkSeries('cloud', name1, series1);
			checkSeries('cloud', name2, series2);
			output.clouds.push({ series1, series2, color1, color2, name1, name2, opacity });
		},
		color_candles: colors => {
			if (output.candleColors) { throw new ScriptError('color_candles called twice'); }
			checkSeries('color_candles', 'colors', colors);
			output.candleColors = colors;
		},
		register_signal: (series, name) => {
			claimName('signal', name);
			checkSeries('signal', name, series);
			output.signals.push({ name, series });
		},
		paint_overlay: (name, params, definition) => {
			claimName('overlay', name);
			if (!definition || !Array.isArray(definition.rows)) { throw new ScriptError('overlay definition needs rows'); }
			JSON.stringify(definition); // must be serializable
			output.overlays.push({ name, params, definition });
		},
		console
	};

	const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
	const names = Object.keys(api);
	const script = new AsyncFunction(...names, `'use strict';\n${source}`);
	await script(...names.map(name => api[name]));
	return output;
}

module.exports = { runIndicator, aggregateCandles, makeIndicatorMath, ScriptError };
