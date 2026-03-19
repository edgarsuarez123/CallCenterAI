const { chromium } = require('playwright');
const { wrap, configure } = require('agentql');

const AGENTQL_API_KEY = process.env.AGENTQL_API_KEY;

// NextGen URL fragment: any substring that appears in your NextGen tab's URL.
// Examples: "nextgen", "ehr", "scheduling", or your hostname like "myclinic.nextgen.com"
// The script finds the Chrome tab whose URL contains this string.
const NEXTGEN_URL_FRAGMENT = 'nextgen';

// AgentQL natural-language query for the button to click (adjust if needed).
const BUTTON_QUERY = '{ book_appointment_button }';

if (!AGENTQL_API_KEY) {
  console.error('Set AGENTQL_API_KEY in PowerShell: $env:AGENTQL_API_KEY = "your-key"');
  process.exit(1);
}

configure({ apiKey: AGENTQL_API_KEY });

async function main() {
  const wsUrl = (await (await fetch('http://localhost:9222/json/version')).json()).webSocketDebuggerUrl;
  if (!wsUrl) {
    console.error('Chrome not running with --remote-debugging-port=9222');
    process.exit(1);
  }

  const browser = await chromium.connectOverCDP(wsUrl);
  const context = browser.contexts()[0];
  const pages = context.pages();
  const page = pages.find(p => p.url().toLowerCase().includes(NEXTGEN_URL_FRAGMENT));

  if (!page) {
    console.error('No tab found with URL containing:', NEXTGEN_URL_FRAGMENT);
    console.log('Open tabs:', pages.map(p => p.url()));
    await browser.close();
    process.exit(1);
  }

  const agentqlPage = wrap(page);
  const response = await agentqlPage.queryElements(BUTTON_QUERY);
  const key = Object.keys(response)[0];
  const locator = response[key];

  if (!locator) {
    console.error('Button not found. Query:', BUTTON_QUERY);
    await browser.close();
    process.exit(1);
  }

  await locator.click();
  console.log('Clicked:', key);
  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
