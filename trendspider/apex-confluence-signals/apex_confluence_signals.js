// =============================================================================
//  APEX Confluence Signals  (v1.0)
//  Buy/Sell signal indicator for TrendSpider
//
//  WHAT IT DOES
//  An ATR trailing stop decides the trend (the "regime"). A BUY or SELL only
//  fires when the regime turns AND enough of 6 independent checks agree:
//
//    1. Trend     close is on the right side of a rising/falling EMA
//    2. RSI       RSI above 50 (buy) or below 50 (sell)
//    3. MACD      MACD line above (buy) or below (sell) its signal line
//    4. ADX       ADX rising (trend gaining strength) and the matching DI leads
//    5. Volume    volume above its average (counts as a pass if no volume data)
//    6. HTF       previous closed higher-time-frame candle agrees with the trend
//
//  If the checks are not there on the flip candle, the signal can still fire
//  a few candles later (the "late-entry window") once they line up. At most
//  one signal is given per regime, so the chart stays clean.
//
//  Each signal gets an entry, a stop (the trailing line) and three targets
//  measured in R (multiples of the initial risk). The trade is closed when
//  the trailing stop flips. The dashboard scores every past signal on the
//  chart, so you can see how the settings perform on this symbol and time
//  frame before trusting them.
//
//  NO REPAINTING
//  Everything uses closed-candle values. The higher time frame uses the
//  previous *closed* HTF candle only. A signal on the last (still forming)
//  candle is provisional until that candle closes, so set alerts to trigger
//  on candle close.
// =============================================================================

describe_indicator('APEX Confluence Signals', 'price', {
	shortName: 'APEX',
	decimals: 'by_symbol',
	warmup: 200
});

// -----------------------------------------------------------------------------
//  Inputs
// -----------------------------------------------------------------------------

const signalTab = input.tab('Signals');
const atrLength = signalTab.number('ATR length', 14, { min: 2, max: 100 });
const atrMultiplier = signalTab.number('ATR multiplier', 3, { min: 0.5, max: 10 });
const minConfirmations = signalTab.number('Min confirmations (of 6)', 4, { min: 0, max: 6 });
const lateEntryWindow = signalTab.number('Late-entry window (candles)', 8, { min: 0, max: 50 });
const tradeDirection = signalTab.select('Trade direction', 'Long & Short', ['Long & Short', 'Long only', 'Short only']);

const filterTab = input.tab('Filters');
const trendEmaLength = filterTab.number('Trend EMA length', 50, { min: 5, max: 400 });
const rsiLength = filterTab.number('RSI length', 14, { min: 2, max: 100 });
const macdRow = filterTab.row();
const macdFastLength = macdRow.number('MACD fast', 12, { min: 2, max: 100 });
const macdSlowLength = macdRow.number('MACD slow', 26, { min: 3, max: 200 });
const macdSignalLength = macdRow.number('MACD signal', 9, { min: 2, max: 100 });
const adxLength = filterTab.number('ADX length', 14, { min: 2, max: 100 });
const volumeAverageLength = filterTab.number('Volume average length', 20, { min: 2, max: 200 });
const volumeFactor = filterTab.number('Volume factor', 1.0, { min: 0, max: 5 });
const higherTimeFrameSetting = filterTab.select('Higher time frame', 'Auto', ['Auto', 'Off', '60', 'D', 'W', 'M']);
const higherTimeFrameEmaLength = filterTab.number('HTF EMA length', 20, { min: 2, max: 200 });

const targetTab = input.tab('Targets');
const target1R = targetTab.number('Target 1 (R)', 1, { min: 0.1, max: 20 });
const target2R = targetTab.number('Target 2 (R)', 2, { min: 0.1, max: 20 });
const target3R = targetTab.number('Target 3 (R)', 3, { min: 0.1, max: 20 });
const tradeManagement = targetTab.select('Trade management', 'Trail only',
	['Trail only', 'Breakeven after T1', 'Scale out at targets']);

const displayTab = input.tab('Display');
const colorCandlesEnabled = displayTab.boolean('Color candles', true);
const showTargets = displayTab.boolean('Show entry and targets', true);
const showTrendCloud = displayTab.boolean('Show trend cloud', true);
const showDashboard = displayTab.boolean('Show dashboard', true);
const dashboardPosition = displayTab.select('Dashboard position', 'top_right',
	['top_left', 'center_left', 'bottom_left', 'top_right', 'center_right', 'bottom_right']);

assert(macdFastLength < macdSlowLength, 'MACD fast length must be smaller than MACD slow length.');
assert(target1R < target2R && target2R < target3R, 'Targets must increase: Target 1 < Target 2 < Target 3.');

// -----------------------------------------------------------------------------
//  Constants and small helpers
// -----------------------------------------------------------------------------

const CANDLE_COUNT = close.length;
assert(CANDLE_COUNT >= 30, 'Not enough candles on the chart for APEX (need at least 30).');

const LONG = 1;
const SHORT = -1;
const COMPONENT_NAMES = ['Trend', 'RSI', 'MACD', 'ADX', 'Volume', 'HTF'];
const MAX_SCORE = COMPONENT_NAMES.length;
const ADX_SLOPE_CANDLES = 3;

const COLORS = {
	bull: '#22c55e',
	bullStrong: '#00e676',
	bullWeak: '#4d7a5c',
	bear: '#ef4444',
	bearStrong: '#ff1744',
	bearWeak: '#8a5252',
	neutral: '#8b93a7',
	target: '#38bdf8',
	entry: '#a1a1aa',
	ema: '#f5b942'
};

const isNumber = value => typeof value === 'number' && Number.isFinite(value);

const priceDecimals = isNumber(current.decimals) ? current.decimals : 2;
const formatPrice = value => (isNumber(value) ? value.toFixed(priceDecimals) : '—');
const formatR = value => (isNumber(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}R` : '—');
const formatPercent = value => (isNumber(value) ? `${value.toFixed(0)}%` : '—');

// EMA that skips empty values, so it can smooth series which start with nulls
// (like MACD, which is empty until the slow EMA has warmed up).
function emaOfSparse(values, length) {
	const smoothing = 2 / (length + 1);
	const result = series_of(null);
	let previous = null;
	let seedSum = 0;
	let seedCount = 0;

	for (let index = 0; index < values.length; index += 1) {
		const value = values[index];

		if (!isNumber(value)) {
			continue;
		}

		if (previous === null) {
			seedSum += value;
			seedCount += 1;

			if (seedCount === length) {
				previous = seedSum / length;
				result[index] = previous;
			}

			continue;
		}

		previous = smoothing * value + (1 - smoothing) * previous;
		result[index] = previous;
	}

	return result;
}

// Carries the last known value forward over empty slots.
function forwardFill(values) {
	let lastValue = null;
	return values.map(value => {
		if (value !== null && value !== undefined) {
			lastValue = value;
		}
		return lastValue;
	});
}

// Approximate length of a time frame in minutes, used to compare time frames.
function timeFrameMinutes(resolution) {
	const minutes = Number(resolution);

	if (isNumber(minutes)) {
		return minutes;
	}

	const minutesByCode = { D: 1440, W: 10080, M: 43200, Q: 129600, Y: 525600 };
	return minutesByCode[resolution] || null;
}

function pickHigherTimeFrame(chartResolution, setting) {
	if (setting === 'Off') {
		return null;
	}

	if (setting !== 'Auto') {
		return setting;
	}

	const chartMinutes = timeFrameMinutes(chartResolution);

	if (!isNumber(chartMinutes)) {
		return null;
	}

	if (chartMinutes < 30) {
		return '60';
	}

	if (chartMinutes < 1440) {
		return 'D';
	}

	if (chartMinutes < 10080) {
		return 'W';
	}

	if (chartMinutes < 43200) {
		return 'M';
	}

	return null;
}

// -----------------------------------------------------------------------------
//  Higher time frame trend (+1 bull, -1 bear, 0 unknown) for every candle
// -----------------------------------------------------------------------------

let higherTimeFrameTrend = series_of(0);
let higherTimeFrameStatus = 'Off';
const higherTimeFrame = pickHigherTimeFrame(current.resolution, higherTimeFrameSetting);
const chartMinutes = timeFrameMinutes(current.resolution);
const higherMinutes = timeFrameMinutes(higherTimeFrame);

if (higherTimeFrame && isNumber(chartMinutes) && isNumber(higherMinutes) && higherMinutes <= chartMinutes) {
	higherTimeFrameStatus = 'Not higher';
}
else if (higherTimeFrame) {
	try {
		const higherData = await request.history(current.ticker, higherTimeFrame);
		const hasEnoughData = higherData && !higherData.error && higherData.close &&
			higherData.close.length > higherTimeFrameEmaLength + 1;

		if (!hasEnoughData) {
			higherTimeFrameStatus = 'No data';
		}
		else {
			const higherEma = ema(higherData.close, higherTimeFrameEmaLength);
			const trendPerHigherCandle = higherData.close.map((higherClose, index) => {
				const emaValue = higherEma[index];

				if (!isNumber(higherClose) || !isNumber(emaValue)) {
					return 0;
				}

				return higherClose > emaValue ? LONG : (higherClose < emaValue ? SHORT : 0);
			});

			// A higher-time-frame candle's trend is only known after it closes, so each
			// HTF candle carries the trend of the HTF candle before it. No lookahead.
			const confirmedTrend = [0, ...trendPerHigherCandle.slice(0, -1)];
			const landedTrend = land_points_onto_series(higherData.time, confirmedTrend, time, 'ge');

			higherTimeFrameTrend = forwardFill(landedTrend).map(value => (isNumber(value) ? value : 0));
			higherTimeFrameStatus = higherTimeFrame;
		}
	}
	catch (error) {
		higherTimeFrameStatus = 'No data';
	}
}

// -----------------------------------------------------------------------------
//  Base indicators
// -----------------------------------------------------------------------------

const trendEma = ema(close, trendEmaLength);
const rsiValues = rsi(close, rsiLength);
const macdLine = for_every(ema(close, macdFastLength), ema(close, macdSlowLength),
	(fast, slow) => (isNumber(fast) && isNumber(slow) ? fast - slow : null));
const macdSignal = emaOfSparse(macdLine, macdSignalLength);
const adxResult = indicators.adx(adxLength);
const averageVolume = sma(volume, volumeAverageLength);
const atrValues = atr(atrLength);
const volumeAvailable = current.volumeDataAvailable !== false;

// -----------------------------------------------------------------------------
//  ATR trailing stop: decides the regime and gives the stop level
// -----------------------------------------------------------------------------

const regime = series_of(0);
const trailingStop = series_of(null);

{
	let upperBand = null;
	let lowerBand = null;
	let direction = 0;

	for (let index = 0; index < CANDLE_COUNT; index += 1) {
		const atrValue = atrValues[index];

		if (!isNumber(atrValue) || !isNumber(close[index])) {
			continue;
		}

		const midpoint = (high[index] + low[index]) / 2;
		const basicUpper = midpoint + atrMultiplier * atrValue;
		const basicLower = midpoint - atrMultiplier * atrValue;

		if (direction === 0) {
			upperBand = basicUpper;
			lowerBand = basicLower;
			direction = close[index] >= midpoint ? LONG : SHORT;
		}
		else {
			const previousClose = close[index - 1];
			upperBand = (basicUpper < upperBand || previousClose > upperBand) ? basicUpper : upperBand;
			lowerBand = (basicLower > lowerBand || previousClose < lowerBand) ? basicLower : lowerBand;

			if (direction === SHORT && close[index] > upperBand) {
				direction = LONG;
			}
			else if (direction === LONG && close[index] < lowerBand) {
				direction = SHORT;
			}
		}

		regime[index] = direction;
		trailingStop[index] = direction === LONG ? lowerBand : upperBand;
	}
}

// -----------------------------------------------------------------------------
//  Confluence: which of the 6 checks pass for each side, on every candle
// -----------------------------------------------------------------------------

function checksAt(index, side) {
	const closeValue = close[index];
	const emaValue = trendEma[index];
	const previousEma = index > 0 ? trendEma[index - 1] : null;
	const rsiValue = rsiValues[index];
	const macdValue = macdLine[index];
	const macdSignalValue = macdSignal[index];
	const adxValue = adxResult.adx[index];
	const previousAdx = index >= ADX_SLOPE_CANDLES ? adxResult.adx[index - ADX_SLOPE_CANDLES] : null;
	const plusDi = adxResult.dmiPlus[index];
	const minusDi = adxResult.dmiMinus[index];
	const volumeValue = volume[index];
	const averageVolumeValue = averageVolume[index];
	const higherTrend = higherTimeFrameTrend[index];
	const isLong = side === LONG;

	const trendPass = isNumber(closeValue) && isNumber(emaValue) && isNumber(previousEma) &&
		(isLong ? closeValue > emaValue && emaValue > previousEma : closeValue < emaValue && emaValue < previousEma);

	const rsiPass = isNumber(rsiValue) && (isLong ? rsiValue > 50 : rsiValue < 50);

	const macdPass = isNumber(macdValue) && isNumber(macdSignalValue) &&
		(isLong ? macdValue > macdSignalValue : macdValue < macdSignalValue);

	// ADX rising = the move is gaining strength. The ADX *level* is not used: right
	// after a flip, a high ADX still describes the old trend, not the new one.
	const adxPass = isNumber(adxValue) && isNumber(previousAdx) && isNumber(plusDi) && isNumber(minusDi) &&
		adxValue > previousAdx && (isLong ? plusDi > minusDi : minusDi > plusDi);

	// No volume data (indices, some FX): this check can't fail, so it doesn't block signals.
	const volumePass = !volumeAvailable ||
		(isNumber(volumeValue) && isNumber(averageVolumeValue) && volumeValue > volumeFactor * averageVolumeValue);

	// Unknown HTF trend counts as a pass; only a confirmed opposite HTF trend fails.
	const higherPass = higherTrend !== (isLong ? SHORT : LONG);

	return [trendPass, rsiPass, macdPass, adxPass, volumePass, higherPass];
}

const countPasses = checks => checks.reduce((total, passed) => total + (passed ? 1 : 0), 0);
const bullScore = series_of(null);
const bearScore = series_of(null);

for (let index = 0; index < CANDLE_COUNT; index += 1) {
	if (isNumber(trailingStop[index])) {
		bullScore[index] = countPasses(checksAt(index, LONG));
		bearScore[index] = countPasses(checksAt(index, SHORT));
	}
}

// -----------------------------------------------------------------------------
//  Signals, trades and targets (one pass over the candles, oldest first)
// -----------------------------------------------------------------------------

const longsAllowed = tradeDirection !== 'Short only';
const shortsAllowed = tradeDirection !== 'Long only';
const targetMultiples = [target1R, target2R, target3R];
const breakevenEnabled = tradeManagement !== 'Trail only';
const scaleOutEnabled = tradeManagement === 'Scale out at targets';

const buySignal = series_of(false);
const sellSignal = series_of(false);
const strongBuySignal = series_of(false);
const strongSellSignal = series_of(false);
const longExitSignal = series_of(false);
const shortExitSignal = series_of(false);
const bullRegimeSignal = regime.map(direction => direction === LONG);
const bearRegimeSignal = regime.map(direction => direction === SHORT);

const buyLabels = series_of(null);
const sellLabels = series_of(null);
const longExitLabels = series_of(null);
const shortExitLabels = series_of(null);
const longTargetLabels = series_of(null);
const shortTargetLabels = series_of(null);

const entryLine = series_of(null);
const target1Line = series_of(null);
const target2Line = series_of(null);
const target3Line = series_of(null);

const closedTrades = [];
let openTrade = null;
let regimeStartIndex = 0;
let regimeAlreadySignaled = true; // the regime in progress during warm-up never signals
let previousDirection = 0;

// Closes what is left of the open trade at `exitPrice` and records the result.
function closeTrade(index, exitPrice, exitText) {
	const remainderR = openTrade.side * (exitPrice - openTrade.entry) / openTrade.risk;
	const resultR = openTrade.realizedR + openTrade.openFraction * remainderR;

	closedTrades.push({
		side: openTrade.side,
		resultR,
		targetsHit: openTrade.targetsHit.slice(),
		bars: index - openTrade.entryIndex
	});

	if (openTrade.side === LONG) {
		longExitSignal[index] = true;
		longExitLabels[index] = exitText;
	}
	else {
		shortExitSignal[index] = true;
		shortExitLabels[index] = exitText;
	}

	openTrade = null;
}

for (let index = 0; index < CANDLE_COUNT; index += 1) {
	const direction = regime[index];

	if (direction !== previousDirection) {
		if (previousDirection !== 0) {
			regimeAlreadySignaled = false;
		}
		regimeStartIndex = index;
		previousDirection = direction;
	}

	// 1. Breakeven stop (armed on an earlier candle, once Target 1 was reached).
	//    Filled at the entry price, or at the open if the candle gapped through it.
	if (openTrade && openTrade.breakevenArmed) {
		const isLong = openTrade.side === LONG;
		const touched = isLong ? low[index] <= openTrade.entry : high[index] >= openTrade.entry;

		if (touched) {
			const fillPrice = isLong ? Math.min(open[index], openTrade.entry) : Math.max(open[index], openTrade.entry);
			closeTrade(index, fillPrice, 'BE');
		}
	}

	// 2. The trailing stop flipped against the open trade: close it at the close.
	if (openTrade && direction !== openTrade.side) {
		closeTrade(index, close[index], '✕');
	}

	// 3. Targets reached by this candle (from the candle after entry).
	if (openTrade && index > openTrade.entryIndex) {
		openTrade.targets.forEach((targetPrice, targetIndex) => {
			if (!openTrade || openTrade.targetsHit[targetIndex]) {
				return;
			}

			const reached = openTrade.side === LONG ? high[index] >= targetPrice : low[index] <= targetPrice;

			if (!reached) {
				return;
			}

			openTrade.targetsHit[targetIndex] = true;
			const labels = openTrade.side === LONG ? longTargetLabels : shortTargetLabels;
			labels[index] = `T${targetIndex + 1}`;

			// Scale out: book a third at Target 1 and a third at Target 2;
			// the last third keeps riding the trailing stop.
			if (scaleOutEnabled && targetIndex < 2) {
				openTrade.realizedR += targetMultiples[targetIndex] / 3;
				openTrade.openFraction -= 1 / 3;
			}
		});

		if (openTrade && breakevenEnabled && openTrade.targetsHit[0]) {
			openTrade.breakevenArmed = true;
		}
	}

	// 4. New signal: first candle in this regime with enough confirmations,
	//    as long as we're still inside the late-entry window.
	const insideWindow = index - regimeStartIndex <= lateEntryWindow;

	if (!regimeAlreadySignaled && direction !== 0 && insideWindow) {
		const score = direction === LONG ? bullScore[index] : bearScore[index];

		if (isNumber(score) && score >= minConfirmations) {
			regimeAlreadySignaled = true;
			const isStrong = score === MAX_SCORE;
			const sideAllowed = direction === LONG ? longsAllowed : shortsAllowed;

			if (sideAllowed) {
				const entryPrice = close[index];
				const stopDistance = Math.abs(entryPrice - trailingStop[index]);
				const risk = stopDistance > 0 ? stopDistance : (atrValues[index] || entryPrice * 0.01);

				openTrade = {
					side: direction,
					entry: entryPrice,
					risk,
					entryIndex: index,
					targets: targetMultiples.map(multiple => entryPrice + direction * multiple * risk),
					targetsHit: [false, false, false],
					breakevenArmed: false,
					realizedR: 0,
					openFraction: 1
				};

				const labelText = `${isStrong ? '★ ' : ''}${direction === LONG ? 'BUY' : 'SELL'} ${score}/${MAX_SCORE}`;

				if (direction === LONG) {
					buySignal[index] = true;
					strongBuySignal[index] = isStrong;
					buyLabels[index] = labelText;
				}
				else {
					sellSignal[index] = true;
					strongSellSignal[index] = isStrong;
					sellLabels[index] = labelText;
				}
			}
		}
	}

	// 5. Entry and target levels, drawn while a trade is open. On a reversal
	//    candle they start one candle later, so the old and new levels don't join up.
	const isReversalCandle = index > 0 && entryLine[index - 1] !== null;

	if (openTrade && (index > openTrade.entryIndex || !isReversalCandle)) {
		entryLine[index] = openTrade.entry;
		target1Line[index] = openTrade.targets[0];
		target2Line[index] = openTrade.targets[1];
		target3Line[index] = openTrade.targets[2];
	}

	// 6. On a reversal candle the new BUY/SELL label already says it all,
	//    so drop the exit mark that would sit on top of it.
	if (buySignal[index]) {
		shortExitLabels[index] = null;
	}
	if (sellSignal[index]) {
		longExitLabels[index] = null;
	}
}

// -----------------------------------------------------------------------------
//  Painting (every paint call runs on every execution, with fixed names)
// -----------------------------------------------------------------------------

const hiddenSeries = series_of(null);
const bullStop = trailingStop.map((value, index) => (regime[index] === LONG ? value : null));
const bearStop = trailingStop.map((value, index) => (regime[index] === SHORT ? value : null));

paint(bullStop, { name: 'Bull Stop', color: COLORS.bull, thickness: 2 });
paint(bearStop, { name: 'Bear Stop', color: COLORS.bear, thickness: 2 });
paint(trendEma, { name: 'Trend EMA', color: COLORS.ema, thickness: 1, invisibleByDefault: true });

color_cloud(
	showTrendCloud ? hl2 : hiddenSeries,
	showTrendCloud ? trailingStop : hiddenSeries,
	COLORS.bull,
	COLORS.bear,
	'Bull Cloud',
	'Bear Cloud',
	0.08
);

paint(showTargets ? entryLine : hiddenSeries, { name: 'Entry', color: COLORS.entry, style: 'ladder', ignoreWhenScaling: true });
paint(showTargets ? target1Line : hiddenSeries, { name: 'Target 1', color: COLORS.target, style: 'ladder', ignoreWhenScaling: true });
paint(showTargets ? target2Line : hiddenSeries, { name: 'Target 2', color: COLORS.target, style: 'ladder', ignoreWhenScaling: true });
paint(showTargets ? target3Line : hiddenSeries, { name: 'Target 3', color: COLORS.target, style: 'ladder', ignoreWhenScaling: true });

paint(buyLabels, {
	name: 'Buy Labels',
	style: 'labels_below',
	color: '#ffffff',
	backgroundColor: COLORS.bull,
	backgroundOpacity: 0.9,
	fontSize: 11,
	verticalOffset: 6
});
paint(sellLabels, {
	name: 'Sell Labels',
	style: 'labels_above',
	color: '#ffffff',
	backgroundColor: COLORS.bear,
	backgroundOpacity: 0.9,
	fontSize: 11,
	verticalOffset: 6
});
paint(longExitLabels, { name: 'Long Exit Labels', style: 'labels_above', color: COLORS.bull, fontSize: 12 });
paint(shortExitLabels, { name: 'Short Exit Labels', style: 'labels_below', color: COLORS.bear, fontSize: 12 });
paint(showTargets ? longTargetLabels : hiddenSeries, { name: 'Long Target Labels', style: 'labels_above', color: COLORS.target, fontSize: 10 });
paint(showTargets ? shortTargetLabels : hiddenSeries, { name: 'Short Target Labels', style: 'labels_below', color: COLORS.target, fontSize: 10 });

// Scores are not drawn, but they can be used in scanners and strategies
// (for example "APEX Bull Score >= 5").
paint(bullScore, { name: 'Bull Score', hidden: true, ignoreWhenScaling: true, editorHidden: true });
paint(bearScore, { name: 'Bear Score', hidden: true, ignoreWhenScaling: true, editorHidden: true });

// Candle colors: regime decides green/red, confluence decides how bright.
function candleColorAt(index) {
	const direction = regime[index];

	if (direction === LONG) {
		const score = bullScore[index];
		return score === MAX_SCORE ? COLORS.bullStrong : (score >= minConfirmations ? COLORS.bull : COLORS.bullWeak);
	}

	if (direction === SHORT) {
		const score = bearScore[index];
		return score === MAX_SCORE ? COLORS.bearStrong : (score >= minConfirmations ? COLORS.bear : COLORS.bearWeak);
	}

	return null;
}

color_candles(colorCandlesEnabled ? regime.map((direction, index) => candleColorAt(index)) : series_of(null));

// -----------------------------------------------------------------------------
//  Signals for scanners, alerts and the Strategy Tester
// -----------------------------------------------------------------------------

register_signal(buySignal, 'Buy');
register_signal(sellSignal, 'Sell');
register_signal(strongBuySignal, 'Strong Buy');
register_signal(strongSellSignal, 'Strong Sell');
register_signal(longExitSignal, 'Long Exit');
register_signal(shortExitSignal, 'Short Exit');
register_signal(bullRegimeSignal, 'Bull Regime');
register_signal(bearRegimeSignal, 'Bear Regime');

// -----------------------------------------------------------------------------
//  Dashboard
// -----------------------------------------------------------------------------

function summarizeTrades(trades) {
	const wins = trades.filter(trade => trade.resultR > 0);
	const grossWin = wins.reduce((total, trade) => total + trade.resultR, 0);
	const grossLoss = trades.filter(trade => trade.resultR <= 0).reduce((total, trade) => total - trade.resultR, 0);
	const netR = trades.reduce((total, trade) => total + trade.resultR, 0);
	const targetHitRate = targetIndex => (trades.length
		? 100 * trades.filter(trade => trade.targetsHit[targetIndex]).length / trades.length
		: null);

	return {
		count: trades.length,
		winRate: trades.length ? 100 * wins.length / trades.length : null,
		averageR: trades.length ? netR / trades.length : null,
		netR: trades.length ? netR : null,
		profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : null),
		target1Rate: targetHitRate(0),
		target2Rate: targetHitRate(1),
		target3Rate: targetHitRate(2)
	};
}

const lastIndex = CANDLE_COUNT - 1;
const lastDirection = regime[lastIndex];
const stats = summarizeTrades(closedTrades);
const lastChecks = lastDirection === SHORT ? checksAt(lastIndex, SHORT) : checksAt(lastIndex, LONG);
const lastScore = countPasses(lastChecks);

const textStyle = { color: 'var(--text-color)', padding: '2px 8px', fontSize: '12px', whiteSpace: 'nowrap' };
const mutedStyle = Object.assign({}, textStyle, { opacity: 0.65 });
const valueStyle = Object.assign({}, textStyle, { textAlign: 'right', fontWeight: 'bold' });
const sectionStyle = Object.assign({}, textStyle, {
	fontSize: '11px',
	fontWeight: 'bold',
	opacity: 0.8,
	paddingTop: '6px',
	borderTop: '1px solid var(--border-color)',
	letterSpacing: '0.5px'
});

const row = (label, value, valueColor) => ({
	cells: [
		Object.assign({ text: label }, mutedStyle),
		Object.assign({ text: value }, valueStyle, valueColor ? { color: valueColor } : {})
	]
});
const section = title => ({ cells: [Object.assign({ text: title, colspan: 2 }, sectionStyle)] });

function positionRows() {
	if (!openTrade) {
		const regimeText = lastDirection === LONG ? 'Bull regime' : (lastDirection === SHORT ? 'Bear regime' : 'Warming up');
		return [{
			cells: [
				Object.assign({ text: 'FLAT', colspan: 1 }, valueStyle, { textAlign: 'left', fontSize: '15px' }),
				Object.assign({ text: regimeText }, mutedStyle, { textAlign: 'right' })
			]
		}];
	}

	const isLong = openTrade.side === LONG;
	const sideColor = isLong ? COLORS.bull : COLORS.bear;
	const openR = openTrade.realizedR +
		openTrade.openFraction * openTrade.side * (close[lastIndex] - openTrade.entry) / openTrade.risk;
	const activeStop = openTrade.breakevenArmed
		? (isLong ? Math.max(trailingStop[lastIndex], openTrade.entry) : Math.min(trailingStop[lastIndex], openTrade.entry))
		: trailingStop[lastIndex];
	const barsOpen = lastIndex - openTrade.entryIndex;
	const targetText = targetIndex => `${formatPrice(openTrade.targets[targetIndex])}${openTrade.targetsHit[targetIndex] ? '  ✓' : ''}`;

	return [{
		cells: [
			Object.assign({ text: isLong ? '▲ LONG' : '▼ SHORT' }, valueStyle, { textAlign: 'left', fontSize: '15px', color: sideColor }),
			Object.assign({ text: `${formatR(openR)} · ${barsOpen} bars` }, valueStyle, { color: openR >= 0 ? COLORS.bull : COLORS.bear })
		]
	},
	row('Entry', formatPrice(openTrade.entry)),
	row(openTrade.breakevenArmed ? 'Stop (breakeven+)' : 'Trailing stop', formatPrice(activeStop), sideColor),
	row(`Target 1 (${target1R}R)`, targetText(0), COLORS.target),
	row(`Target 2 (${target2R}R)`, targetText(1), COLORS.target),
	row(`Target 3 (${target3R}R)`, targetText(2), COLORS.target)];
}

function confluenceRows() {
	const sideName = lastDirection === SHORT ? 'bear' : 'bull';
	const detailByComponent = {
		Trend: `EMA ${formatPrice(trendEma[lastIndex])}`,
		RSI: isNumber(rsiValues[lastIndex]) ? rsiValues[lastIndex].toFixed(1) : '—',
		MACD: isNumber(macdLine[lastIndex]) && isNumber(macdSignal[lastIndex])
			? (macdLine[lastIndex] - macdSignal[lastIndex]).toFixed(priceDecimals + 1)
			: '—',
		ADX: isNumber(adxResult.adx[lastIndex]) ? adxResult.adx[lastIndex].toFixed(1) : '—',
		Volume: !volumeAvailable ? 'n/a'
			: (isNumber(volume[lastIndex]) && isNumber(averageVolume[lastIndex]) && averageVolume[lastIndex] > 0
				? `${(volume[lastIndex] / averageVolume[lastIndex]).toFixed(2)}× avg`
				: '—'),
		HTF: higherTimeFrameStatus === higherTimeFrame && higherTimeFrame
			? `${higherTimeFrame} ${higherTimeFrameTrend[lastIndex] === LONG ? 'up' : (higherTimeFrameTrend[lastIndex] === SHORT ? 'down' : '—')}`
			: higherTimeFrameStatus
	};

	return [section(`CONFLUENCE  ${lastScore}/${MAX_SCORE} ${sideName}`)].concat(
		COMPONENT_NAMES.map((componentName, componentIndex) => {
			const passed = lastChecks[componentIndex];
			return {
				cells: [
					Object.assign({ text: `${passed ? '✓' : '✕'}  ${componentName}` }, textStyle, {
						color: passed ? COLORS.bull : COLORS.neutral
					}),
					Object.assign({ text: detailByComponent[componentName] }, mutedStyle, { textAlign: 'right' })
				]
			};
		})
	);
}

function historyRows() {
	const profitFactorText = stats.profitFactor === Infinity ? '∞'
		: (isNumber(stats.profitFactor) ? stats.profitFactor.toFixed(2) : '—');

	return [
		section(`SIGNAL HISTORY  (${stats.count} closed)`),
		row('Win rate', formatPercent(stats.winRate)),
		row('Average / Net', `${formatR(stats.averageR)} / ${formatR(stats.netR)}`,
			isNumber(stats.netR) ? (stats.netR >= 0 ? COLORS.bull : COLORS.bear) : null),
		row('Profit factor', profitFactorText),
		row('Hit T1 / T2 / T3', `${formatPercent(stats.target1Rate)} / ${formatPercent(stats.target2Rate)} / ${formatPercent(stats.target3Rate)}`)
	];
}

const dashboardRows = showDashboard
	? [{
		cells: [Object.assign({
			text: `APEX Confluence · ${current.ticker || ''} ${current.resolution || ''}`,
			colspan: 2
		}, textStyle, { fontWeight: 'bold', fontSize: '13px', paddingBottom: '4px' })]
	}]
		.concat(positionRows())
		.concat(confluenceRows())
		.concat(historyRows())
		.concat([{
			cells: [Object.assign({
				text: 'Closed-candle signals · no repainting · not financial advice',
				colspan: 2
			}, mutedStyle, { fontSize: '10px', paddingTop: '6px' })]
		}])
	: [];

paint_overlay('APEX Dashboard', { position: dashboardPosition }, {
	background: 'var(--background-color)',
	border: '1px solid var(--border-color)',
	borderRadius: '6px',
	padding: '4px',
	opacity: 0.95,
	rows: dashboardRows
});
