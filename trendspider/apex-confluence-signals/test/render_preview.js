// Renders a preview image of the indicator: runs the script under the mock
// runtime, draws what it painted on a canvas (candles, stops, cloud, targets,
// labels) plus the dashboard overlay, and screenshots it with Playwright.
//
//   node test/render_preview.js <data.json> <TICKER> <resolution> <out.png> [visibleCandles]

'use strict';

const fs = require('fs');
const path = require('path');
const { runIndicator } = require('./mock_trendspider');

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

const kebab = name => name.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`);
const escapeHtml = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Turns a paint_overlay() definition into an HTML table, the way TrendSpider does.
function overlayToHtml(definition) {
	const styleOf = element => Object.entries(element)
		.filter(([key]) => !['rows', 'cells', 'text', 'colspan', 'rowspan', 'table', 'chart'].includes(key))
		.map(([key, value]) => `${kebab(key)}:${typeof value === 'number' && key !== 'opacity' ? `${value}px` : value}`)
		.join(';');
	const rows = definition.rows.map(row => `<tr style="${styleOf(row)}">${row.cells.map(cell =>
		`<td${cell.colspan ? ` colspan="${cell.colspan}"` : ''} style="${styleOf(cell)}">${escapeHtml(cell.text || '')}</td>`).join('')}</tr>`).join('');
	return `<table style="${styleOf(definition)};border-collapse:separate">${rows}</table>`;
}

async function main() {
	const [dataPath, ticker, resolution, outPath, visibleArg] = process.argv.slice(2);
	const visibleCandles = Number(visibleArg || 260);
	const source = fs.readFileSync(path.join(__dirname, '..', 'apex_confluence_signals.js'), 'utf8');
	const data = loadCandles(dataPath);
	const output = await runIndicator(source, data, { ticker, resolution });

	const from = Math.max(0, data.close.length - visibleCandles);
	const window = series => series.slice(from);
	const paintsByName = Object.fromEntries(output.paints.map(item => [item.name, { series: window(item.series), params: item.params }]));
	const cloud = output.clouds[0];
	const chart = {
		ticker,
		resolution,
		time: window(data.time),
		open: window(data.open),
		high: window(data.high),
		low: window(data.low),
		close: window(data.close),
		candleColors: window(output.candleColors),
		cloud: { upper: window(cloud.series1), lower: window(cloud.series2), color1: cloud.color1, color2: cloud.color2 },
		paints: paintsByName
	};
	const overlayHtml = overlayToHtml(output.overlays[0].definition);

	const html = `<!doctype html><html><head><meta charset="utf-8"><style>
	:root { --background-color:#131a2e; --text-color:#e6e9f2; --text-accent-color:#ffffff; --border-color:#2b3553; --active-element-color:#3b82f6; }
	body { margin:0; background:#0e1424; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
	#wrap { position:relative; width:1600px; height:900px; }
	#overlay { position:absolute; top:44px; right:24px; }
	#title { position:absolute; top:12px; left:18px; color:#e6e9f2; font-size:18px; font-weight:600; }
	#title span { color:#8b93a7; font-weight:400; font-size:14px; margin-left:10px; }
	</style></head><body><div id="wrap"><canvas id="c" width="1600" height="900"></canvas>
	<div id="title">${escapeHtml(ticker)} · ${resolution === 'D' ? 'Daily' : resolution === '60' ? '1 hour' : resolution}<span>APEX Confluence Signals</span></div>
	<div id="overlay">${overlayHtml}</div></div>
	<script>(() => {
	const chart = ${JSON.stringify(chart)};
	const canvas = document.getElementById('c');
	const ctx = canvas.getContext('2d');
	const left = 18, right = 1150, top = 50, bottom = 900 - 40;
	const n = chart.close.length;
	const step = (right - left) / n;
	const x = i => left + step * (i + 0.5);
	const scaled = ['Bull Stop', 'Bear Stop'].flatMap(name => chart.paints[name].series).filter(v => typeof v === 'number');
	const lo = Math.min(...chart.low, ...scaled), hi = Math.max(...chart.high, ...scaled);
	const pad = (hi - lo) * 0.08;
	const yMin = lo - pad, yMax = hi + pad;
	const y = v => bottom - (v - yMin) / (yMax - yMin) * (bottom - top);

	ctx.fillStyle = '#0e1424'; ctx.fillRect(0, 0, 1600, 900);
	ctx.strokeStyle = '#2b3553'; ctx.beginPath(); ctx.moveTo(right + 1, top - 10); ctx.lineTo(right + 1, bottom); ctx.stroke();
	// grid + price axis
	ctx.font = '12px Segoe UI, Roboto, Arial'; ctx.textBaseline = 'middle';
	const tickStep = Math.pow(10, Math.floor(Math.log10((yMax - yMin) / 6)));
	const niceStep = [1, 2, 5, 10].map(m => m * tickStep).find(s => (yMax - yMin) / s <= 8);
	for (let v = Math.ceil(yMin / niceStep) * niceStep; v < yMax; v += niceStep) {
		ctx.strokeStyle = '#1a2340'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(left, y(v)); ctx.lineTo(right, y(v)); ctx.stroke();
		ctx.fillStyle = '#7f88a3'; ctx.fillText(v.toFixed(niceStep < 1 ? 2 : 0), right + 8, y(v));
	}
	// time axis
	ctx.textAlign = 'center';
	const intraday = !['D', 'W', 'M'].includes(chart.resolution);
	let lastKey = null;
	let lastLabelX = -Infinity;
	chart.time.forEach((t, i) => {
		const d = new Date(t * 1000);
		const key = intraday ? d.toISOString().slice(0, 10) : d.getUTCFullYear() * 12 + d.getUTCMonth();
		if (key !== lastKey && i > 3 && x(i) - lastLabelX > 70) {
			const text = intraday
				? d.toLocaleString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' })
				: d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }) + (d.getUTCMonth() === 0 ? ' ' + d.getUTCFullYear() : '');
			ctx.fillStyle = '#7f88a3';
			ctx.fillText(text, x(i), bottom + 20);
			lastLabelX = x(i);
		}
		lastKey = key;
	});
	ctx.textAlign = 'left';

	ctx.save(); ctx.beginPath(); ctx.rect(left, top - 10, right - left, bottom - top + 10); ctx.clip();
	// trend cloud
	for (let i = 1; i < n; i++) {
		const a0 = chart.cloud.upper[i - 1], b0 = chart.cloud.lower[i - 1], a1 = chart.cloud.upper[i], b1 = chart.cloud.lower[i];
		if ([a0, b0, a1, b1].some(v => typeof v !== 'number')) continue;
		ctx.fillStyle = (a1 >= b1 ? chart.cloud.color1 : chart.cloud.color2) + '24';
		ctx.beginPath(); ctx.moveTo(x(i - 1), y(a0)); ctx.lineTo(x(i), y(a1)); ctx.lineTo(x(i), y(b1)); ctx.lineTo(x(i - 1), y(b0)); ctx.closePath(); ctx.fill();
	}

	function drawLine(name, dashed) {
		const item = chart.paints[name];
		const values = item.series;
		ctx.strokeStyle = item.params.color; ctx.lineWidth = item.params.thickness || 1;
		ctx.setLineDash(dashed ? [5, 4] : []);
		const ladder = item.params.style === 'ladder';
		ctx.beginPath();
		let drawing = false;
		for (let i = 0; i < n; i++) {
			const v = values[i];
			if (typeof v !== 'number') { drawing = false; continue; }
			if (!drawing) { ctx.moveTo(ladder ? x(i) - step / 2 : x(i), y(v)); drawing = true; }
			else if (ladder) { ctx.lineTo(x(i) - step / 2, y(values[i - 1])); ctx.lineTo(x(i) - step / 2, y(v)); }
			else { ctx.lineTo(x(i), y(v)); }
			if (ladder) ctx.lineTo(x(i) + step / 2, y(v));
		}
		ctx.stroke(); ctx.setLineDash([]);
	}
	['Entry', 'Target 1', 'Target 2', 'Target 3'].forEach(name => drawLine(name, true));

	// candles
	const bodyWidth = Math.max(1, step * 0.62);
	for (let i = 0; i < n; i++) {
		const color = chart.candleColors[i] || (chart.close[i] >= chart.open[i] ? '#22c55e' : '#ef4444');
		ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
		ctx.beginPath(); ctx.moveTo(x(i), y(chart.high[i])); ctx.lineTo(x(i), y(chart.low[i])); ctx.stroke();
		const yo = y(chart.open[i]), yc = y(chart.close[i]);
		ctx.fillRect(x(i) - bodyWidth / 2, Math.min(yo, yc), bodyWidth, Math.max(1, Math.abs(yo - yc)));
	}
	drawLine('Bull Stop'); drawLine('Bear Stop');

	function drawLabels(name, above) {
		const item = chart.paints[name];
		ctx.font = (item.params.fontSize || 11) + 'px Segoe UI, Roboto, Arial';
		ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
		item.series.forEach((text, i) => {
			if (!text) return;
			const anchor = above ? y(chart.high[i]) : y(chart.low[i]);
			const offset = (item.params.verticalOffset || 2) + 10;
			const cy = above ? anchor - offset : anchor + offset;
			if (item.params.backgroundColor) {
				const w = ctx.measureText(text).width + 10, h = 17;
				ctx.fillStyle = item.params.backgroundColor;
				ctx.beginPath(); ctx.roundRect(x(i) - w / 2, cy - h / 2, w, h, 3); ctx.fill();
				ctx.beginPath();
				if (above) { ctx.moveTo(x(i) - 4, cy + h / 2); ctx.lineTo(x(i) + 4, cy + h / 2); ctx.lineTo(x(i), cy + h / 2 + 5); }
				else { ctx.moveTo(x(i) - 4, cy - h / 2); ctx.lineTo(x(i) + 4, cy - h / 2); ctx.lineTo(x(i), cy - h / 2 - 5); }
				ctx.fill();
			}
			ctx.fillStyle = item.params.color;
			ctx.fillText(text, x(i), cy);
		});
		ctx.textAlign = 'left';
	}
	drawLabels('Long Target Labels', true); drawLabels('Short Target Labels', false);
	drawLabels('Long Exit Labels', true); drawLabels('Short Exit Labels', false);
	drawLabels('Buy Labels', false); drawLabels('Sell Labels', true);
	ctx.restore();
	})();</script></body></html>`;

	const htmlPath = outPath.replace(/\.png$/, '.html');
	fs.writeFileSync(htmlPath, html);
	const { chromium } = require('playwright');
	const browser = await chromium.launch();
	const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
	page.on('pageerror', error => console.error('page error:', error.message));
	await page.goto(`file://${path.resolve(htmlPath)}`);
	await page.screenshot({ path: outPath });
	await browser.close();
	fs.unlinkSync(htmlPath);
	console.log(`wrote ${outPath}`);
}

main().catch(error => {
	console.error(error);
	process.exit(1);
});
