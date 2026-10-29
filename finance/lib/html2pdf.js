// Render an HTML file to A4 PDF with the pre-installed Playwright/Chromium.
// usage: node lib/html2pdf.js in.html out.pdf
const { chromium } = require('playwright');
(async () => {
  const [inPath, outPath] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + require('path').resolve(inPath));
  await page.pdf({ path: outPath, format: 'A4', printBackground: true,
                   margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' } });
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
