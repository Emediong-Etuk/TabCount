// Checks the APEX indicator under the mock TrendSpider runtime.
//
//   node test/run_tests.js                 synthetic data only
//   node test/run_tests.js path/to/data    also every *.json OHLCV file in that folder
//
// Data files can be { time, open, high, low, close, volume } or a raw Yahoo
// Finance chart response. Name them like AAPL_D.json or AAPL_60.json so the
// resolution is known.

'use strict';

const fs = require('fs');
const path = require('path');
const { runIndicator } = require('./mock_trendspider');

const SCRIPT_PATH = path.join(__dirname, '..', 'apex_confluence_signals.js');
const source = fs.readFileSync(SCRIPT_PATH, 'utf8');

let failures = 0;
const check = (condition, message) => {
	if (!condition) {
		failures += 1;
		console.log(`  FAIL ${message}`);
	}
};

// ---------------------------------------------------------------------------
//  Data
// ---------------------------------------------------------------------------

function syntheticCandles(count, seed, startTime = 1577836800, stepSeconds = 86400) {
	let state = seed;
	const random = () => {
		state = (state * 1664525 + 1013904223) % 4294967296;
		return state / 4294967296;
	};
	const data = { time: [], open: [], high: [], low: [], close: [], volume: [] };
	let price = 100;
	let drift = 0.001;
	for (let index = 0; index < count; index += 1) {
		if (random() < 0.02) { drift = (random() - 0.5) * 0.006; }
		const open = price;
		const change = drift + (random() - 0.5) * 0.04;
		const close = Math.max(1, open * (1 + change));
		const high = Math.max(open, close) * (1 + random() * 0.015);
		const low = Math.min(open, close) * (1 - random() * 0.015);
		data.time.push(startTime + index * stepSeconds);
		data.open.push(open);
		data.high.push(high);
		data.low.push(low);
		data.close.push(close);
		data.volume.push(Math.round(1e6 * (0.5 + random() * (Math.abs(change) * 40 + 1))));
		price = close;
	}
	return data;
}

function loadCandles(filePath) {
	const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'));
	if (raw.close) { return raw; }
	const result = raw.chart.result[0];
	const quote = result.indicators.quote[0];
	const data = { time: [], open: [], high: [], low: [], close: [], volume: [] };
	result.timestamp.forEach((timestamp, index) => {
		const values = [quote.open[index], quote.high[index], quote.low[index], quote.close[index]];
		if (values.some(value => typeof value !== 'number')) { return; }
		data.time.push(timestamp);
		data.open.push(values[0]);
		data.high.push(values[1]);
		data.low.push(values[2]);
		data.close.push(values[3]);
		data.volume.push(quote.volume[index] || 0);
	});
	return data;
}

const sliceCandles = (data, count) => Object.fromEntries(Object.entries(data).map(([key, values]) => [key, values.slice(0, count)]));

// ---------------------------------------------------------------------------
//  Helpers over the indicator output
// ---------------------------------------------------------------------------

const signalSeries = (output, name) => output.signals.find(signal => signal.name === name).series;
const paintSeries = (output, name) => output.paints.find(item => item.name === name).series;
const indicesOf = series => series.reduce((list, value, index) => (value ? list.concat(index) : list), []);
const outputShape = output => JSON.stringify({
	paints: output.paints.map(item => item.name),
	signals: output.signals.map(item => item.name),
	clouds: output.clouds.map(item => item.name1),
	overlays: output.overlays.map(item => item.name),
	candles: Boolean(output.candleColors)
});

function tradeStats(output) {
	const rows = output.overlays[0].definition.rows;
	const historyStart = rows.findIndex(row => /SIGNAL HISTORY/.test(row.cells[0].text));
	if (historyStart < 0) { return 'dashboard hidden'; }
	return rows.slice(historyStart, historyStart + 5).map(row => row.cells.map(cell => cell.text).join(' ')).join(' | ');
}

// ---------------------------------------------------------------------------
//  Tests
// ---------------------------------------------------------------------------

// Same paint/signal names in the same order, whatever the inputs or data.
async function testStableOutputs(data) {
	console.log('• outputs are identical in shape across inputs and data');
	const variants = [
		{},
		{ 'Higher time frame': 'Off' },
		{ 'Show dashboard': false, 'Color candles': false, 'Show entry and targets': false, 'Show trend cloud': false },
		{ 'Trade direction': 'Long only', 'Min confirmations (of 6)': 6 },
		{ 'Trade direction': 'Short only', 'Min confirmations (of 6)': 0, 'Late-entry window (candles)': 0 },
		{ 'Trade management': 'Breakeven after T1' },
		{ 'Trade management': 'Scale out at targets', 'Dashboard position': 'bottom_left' }
	];
	const reference = outputShape(await runIndicator(source, data));
	for (const overrides of variants) {
		const shape = outputShape(await runIndicator(source, data, { inputOverrides: overrides }));
		check(shape === reference, `output names changed with inputs ${JSON.stringify(overrides)}`);
	}
	const noVolume = await runIndicator(source, { ...data, volume: data.volume.map(() => 0) }, { volumeDataAvailable: false });
	check(outputShape(noVolume) === reference, 'output names changed without volume data');
	const shortChart = await runIndicator(source, sliceCandles(data, 40));
	check(outputShape(shortChart) === reference, 'output names changed on a 40-candle chart');
	const failingHistory = await runIndicator(source, data, { historyProvider: async () => { throw new Error('denied'); } });
	check(outputShape(failingHistory) === reference, 'output names changed when request.history fails');
	const errorHistory = await runIndicator(source, data, { historyProvider: async () => ({ error: 'no agreement' }) });
	check(outputShape(errorHistory) === reference, 'output names changed when request.history returns an error');
}

// One signal per regime at most, labels match signals, signals in the right regime.
async function testSignalRules(data, label, resolution) {
	const output = await runIndicator(source, data, { resolution });
	const regimeBull = signalSeries(output, 'Bull Regime');
	const regimeBear = signalSeries(output, 'Bear Regime');
	const buys = indicesOf(signalSeries(output, 'Buy'));
	const sells = indicesOf(signalSeries(output, 'Sell'));
	const buyLabels = indicesOf(paintSeries(output, 'Buy Labels'));
	const sellLabels = indicesOf(paintSeries(output, 'Sell Labels'));

	check(JSON.stringify(buys) === JSON.stringify(buyLabels), `${label}: buy labels don't match buy signals`);
	check(JSON.stringify(sells) === JSON.stringify(sellLabels), `${label}: sell labels don't match sell signals`);
	check(buys.every(index => regimeBull[index]), `${label}: a buy fired outside a bull regime`);
	check(sells.every(index => regimeBear[index]), `${label}: a sell fired outside a bear regime`);

	const regimeId = [];
	let id = 0;
	regimeBull.forEach((bull, index) => {
		if (index > 0 && bull !== regimeBull[index - 1]) { id += 1; }
		regimeId.push(id);
	});
	const signalRegimes = buys.concat(sells).map(index => regimeId[index]);
	check(new Set(signalRegimes).size === signalRegimes.length, `${label}: more than one signal in a regime`);

	const longExits = indicesOf(signalSeries(output, 'Long Exit'));
	const shortExits = indicesOf(signalSeries(output, 'Short Exit'));
	check(longExits.every(index => regimeBear[index]), `${label}: long exit not on a bear flip`);
	check(regimeBull.every((bull, index) => !(bull && regimeBear[index])), `${label}: bull and bear regime at once`);

	// Recount the closed trades from the raw signals and compare with the dashboard.
	const closes = data.close;
	const recount = (entries, exits, stopName, side) => entries.reduce((total, entryIndex) => {
		const exitIndex = exits.find(index => index > entryIndex);
		if (exitIndex === undefined) { return total; }
		const risk = Math.abs(closes[entryIndex] - paintSeries(output, stopName)[entryIndex]);
		return total + side * (closes[exitIndex] - closes[entryIndex]) / risk;
	}, 0);
	const recountedNetR = recount(buys, longExits, 'Bull Stop', 1) + recount(sells, shortExits, 'Bear Stop', -1);
	const dashboardText = output.overlays[0].definition.rows.map(row => row.cells.map(cell => cell.text).join(' ')).join('\n');
	const dashboardNet = Number((dashboardText.match(/Average \/ Net [^/]+\/ ([+-][\d.]+)R/) || [])[1] || 0);
	check(Math.abs(dashboardNet - recountedNetR) < 0.01,
		`${label}: dashboard net ${dashboardNet}R differs from recount ${recountedNetR.toFixed(2)}R`);
	return { output, buys, sells };
}

// Run on growing prefixes of the data: everything already on the chart must
// stay exactly as it was. Catches repainting and higher-time-frame lookahead.
async function testNoRepainting(data, label, resolution, checkpoints) {
	const full = await runIndicator(source, data, { resolution });
	const compared = ['Buy', 'Sell', 'Strong Buy', 'Strong Sell', 'Long Exit', 'Short Exit', 'Bull Regime', 'Bear Regime'];
	const comparedPaints = ['Bull Stop', 'Bear Stop', 'Buy Labels', 'Sell Labels', 'Entry', 'Target 1', 'Bull Score', 'Bear Score'];
	let mismatches = 0;

	for (const count of checkpoints) {
		const partial = await runIndicator(source, sliceCandles(data, count), { resolution });
		for (const name of compared) {
			const before = signalSeries(partial, name);
			const after = signalSeries(full, name).slice(0, count);
			if (JSON.stringify(before.map(Boolean)) !== JSON.stringify(after.map(Boolean))) {
				mismatches += 1;
				check(false, `${label}: signal "${name}" changed after ${count} candles`);
			}
		}
		for (const name of comparedPaints) {
			const before = paintSeries(partial, name);
			const after = paintSeries(full, name).slice(0, count);
			const same = before.every((value, index) => (typeof value === 'number' && typeof after[index] === 'number'
				? Math.abs(value - after[index]) < 1e-9
				: value === after[index]));
			if (!same) {
				mismatches += 1;
				check(false, `${label}: line "${name}" changed after ${count} candles`);
			}
		}
		const colorsBefore = partial.candleColors;
		const colorsAfter = full.candleColors.slice(0, count);
		if (JSON.stringify(colorsBefore) !== JSON.stringify(colorsAfter)) {
			mismatches += 1;
			check(false, `${label}: candle colors changed after ${count} candles`);
		}
	}
	return mismatches;
}

async function main() {
	const synthetic = syntheticCandles(900, 7);

	await testStableOutputs(synthetic);

	console.log('• signal rules (synthetic)');
	const syntheticRun = await testSignalRules(synthetic, 'synthetic', 'D');
	check(syntheticRun.buys.length + syntheticRun.sells.length > 5, 'synthetic: expected some signals');

	console.log('• no repainting (synthetic, weekly HTF)');
	const syntheticCheckpoints = [];
	for (let count = 300; count <= 900; count += 7) { syntheticCheckpoints.push(count); }
	await testNoRepainting(synthetic, 'synthetic', 'D', syntheticCheckpoints);

	const dataDir = process.argv[2];
	if (dataDir) {
		const files = fs.readdirSync(dataDir).filter(name => name.endsWith('.json')).sort();
		console.log(`• real data (${files.length} files)`);
		for (const file of files) {
			const [ticker, resolution] = path.basename(file, '.json').split('_');
			const data = loadCandles(path.join(dataDir, file));
			const label = `${ticker} ${resolution}`;
			const { output, buys, sells } = await testSignalRules(data, label, resolution);
			const checkpoints = [];
			for (let count = data.close.length - 200; count < data.close.length; count += 9) { checkpoints.push(count); }
			const mismatches = await testNoRepainting(data, label, resolution, checkpoints);
			console.log(`  ${label.padEnd(12)} candles ${String(data.close.length).padStart(5)}  buys ${String(buys.length).padStart(3)}  sells ${String(sells.length).padStart(3)}  repaint diffs ${mismatches}  | ${tradeStats(output)}`);
		}
	}

	console.log(failures ? `\n${failures} check(s) failed` : '\nAll checks passed');
	process.exit(failures ? 1 : 0);
}

main().catch(error => {
	console.error(error);
	process.exit(1);
});
