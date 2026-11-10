import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handler } = await import(workerUrl.href);
  const request = new Request("http://localhost/", { headers: { accept: "text/html" } });
  const environment = { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } };
  const context = { waitUntil() {}, passThroughOnException() {} };
  return typeof handler === "function"
    ? handler(request, environment, context)
    : handler.fetch(request, environment, context);
}

test("server-renders the iPad family dashboard shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.doesNotMatch(html, /codex-preview/i);
  assert.match(html, /<title>Familieportalen<\/title>/i);
  assert.match(html, /Familieportalen våkner/);
  assert.doesNotMatch(html, /example data|eksempeldata|react-loading-skeleton/i);
});

test("source keeps the data boundary and functional surfaces explicit", async () => {
  const [page, consoleSource, apiSource, odaSource, dinnerSource, helloFreshSource, helloFreshAccountSource, helloFreshImageSource, deploySource, supervisorSource, portalPlist, imagePlist, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/_components/FamilyConsole.tsx", import.meta.url), "utf8"),
    readFile(new URL("../local_api/familybot_api.py", import.meta.url), "utf8"),
    readFile(new URL("../local_api/oda_mcp.py", import.meta.url), "utf8"),
    readFile(new URL("../local_api/oda_dinner.py", import.meta.url), "utf8"),
    readFile(new URL("../local_api/hellofresh_norway.py", import.meta.url), "utf8"),
    Promise.all(
      [
        "hellofresh_account.py",
        "hellofresh_account_contract.py",
        "hellofresh_account_mutations.py",
        "hellofresh_account_recipe.py",
        "hellofresh_account_transport.py",
      ].map((name) => readFile(new URL(`../local_api/${name}`, import.meta.url), "utf8")),
    ).then((parts) => parts.join("\n")),
    readFile(new URL("../local_api/hellofresh_images.py", import.meta.url), "utf8"),
    readFile(new URL("../scripts/deploy-local.sh", import.meta.url), "utf8"),
    readFile(new URL("../local_service/run_service.py", import.meta.url), "utf8"),
    readFile(new URL("../launchd/ai.familybot.portal.plist", import.meta.url), "utf8"),
    readFile(new URL("../launchd/ai.familybot.portal-images.plist", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(page, /codex-preview/);
  assert.match(consoleSource, /Familiens oversikt/);
  assert.match(consoleSource, /Hva vil du gjøre/);
  assert.match(consoleSource, /Legg til gjøremål/);
  assert.match(consoleSource, /repeat_weekdays/);
  assert.match(consoleSource, /mission-progress/);
  assert.match(consoleSource, /Nullstill begge/);
  assert.match(consoleSource, /Fulle 30-poengsblokker/);
  assert.match(consoleSource, /weekly-achievement/);
  assert.match(consoleSource, /full_tabs/);
  assert.match(consoleSource, /Samlet fremgang/);
  assert.doesNotMatch(consoleSource, /BlockCounter/);
  assert.match(consoleSource, /Aktiv 30-poengsblokk/);
  assert.doesNotMatch(consoleSource, /tally-group|tally-groups|tally-empty/);
  assert.match(consoleSource, /const achievement=child\.weekly_achievement/);
  assert.match(consoleSource, /fullTabs=achievement\?\.full_tabs/);
  assert.match(consoleSource, /blockPoints/);
  assert.match(consoleSource, /blockPercent/);
  assert.match(consoleSource, /JanuaryChoreSummary/);
  assert.match(consoleSource, /annual_chore_summary/);
  assert.match(consoleSource, /function completionKey/);
  assert.match(consoleSource, /sessionToken\.current&&sessionToken\.current!==nextToken/);
  assert.match(consoleSource, /window\.location\.reload\(\)/);
  assert.match(consoleSource, /Skolen denne uken/);
  assert.match(consoleSource, /function renderWeekPlanText/);
  assert.match(consoleSource, /function renderWeekPlanInterpretation/);
  assert.match(consoleSource, /week-plan-interpretation/);
  assert.match(consoleSource, /week-plan-weekly-tasks/);
  assert.match(consoleSource, /week-plan-general-info/);
  assert.match(consoleSource, /week-plan-rich-text/);
  assert.match(consoleSource, /week-plan-list/);
  assert.doesNotMatch(consoleSource, /<pre>\{detail\.full_text\}<\/pre>/);
  assert.match(consoleSource, /Neste 5 dager/);
  assert.match(consoleSource, /function upcomingEventsFor/);
  assert.match(consoleSource, /return upcomingOverview\(data\)/);
  assert.match(consoleSource, /overviewSettings\.showActivitiesCard&&<ActivitiesCard/);
  assert.match(consoleSource, /<WeatherSymbol symbol=\{data.weather.symbol\}/);
  assert.match(consoleSource, /<MetroSymbol/);
  assert.doesNotMatch(consoleSource, /className="weather-advice"/);
  assert.ok(consoleSource.indexOf('className="overview-card transport-card"') < consoleSource.indexOf('className="overview-card weather-card"'));
  assert.match(consoleSource, /Kanban/);
  assert.match(consoleSource, /New/);
  assert.match(consoleSource, /In Progress/);
  assert.match(consoleSource, /Pause/);
  assert.match(consoleSource, /Done/);
  assert.match(consoleSource, /api\/kanban/);
  assert.match(consoleSource, /Kanban er skrivebeskyttet/);
  assert.match(consoleSource, />Oda<\/button>/);
  assert.match(consoleSource, /Hva trenger dere\?/);
  assert.match(consoleSource, /Dette kjøper dere ofte/);
  assert.match(consoleSource, /Se gjennom og betal hos Oda/);
  assert.match(consoleSource, /kan ikke betale eller fullføre bestillingen/);
  assert.match(consoleSource, /api\/oda\/search/);
  assert.match(consoleSource, /Middagsassistent/);
  assert.match(consoleSource, /api\/oda\/dinner/);
  assert.match(consoleSource, /Legg alle ingrediensene i kurven/);
  assert.match(consoleSource, /api\/oda\/recipes\/\$\{recipe\.id\}\/cart/);
  assert.match(consoleSource, /oda-recipe-image/);
  assert.match(consoleSource, /src=\{recipe\.imageUrl\}/);
  assert.match(consoleSource, /referrerPolicy="no-referrer"/);
  assert.match(consoleSource, /oda-recipe-dialog/);
  assert.match(consoleSource, /Tilbake til middagsforslag/);
  assert.match(consoleSource, /recipe\.ingredients/);
  assert.match(consoleSource, /recipe\.instructions/);
  assert.doesNotMatch(consoleSource, /<a href=\{recipe\.url\}>/);
  assert.match(consoleSource, /window\.location\.assign\(result\.authorization_url\)/);
  assert.match(consoleSource, /virker i kioskmodus/);
  assert.doesNotMatch(consoleSource, /window\.open\(|familybot-oda-connect|Tillat sprettoppvindu/);
  assert.doesNotMatch(consoleSource, /Spør FamilyBot|api\/chat|OpenAI/);
  assert.match(consoleSource, /features\.hellofresh/);
  assert.match(consoleSource, />HelloFresh<\/button>/);
  assert.match(consoleSource, /api\/hellofresh\/menu/);
  assert.match(consoleSource, /Kommende matkasser/);
  assert.match(consoleSource, /Deres matkasse/);
  assert.match(consoleSource, /Bytt denne/);
  assert.match(consoleSource, /Sett uken på pause/);
  assert.match(consoleSource, /features\.hellofresh_account/);
  assert.match(consoleSource, /Logg inn hos HelloFresh/);
  assert.match(consoleSource, /autoComplete="current-password"/);
  assert.match(consoleSource, /private hjemmenett/);
  assert.match(consoleSource, /api\/hellofresh\/auth\/login/);
  assert.match(consoleSource, /api\/hellofresh\/account\/menu/);
  assert.match(consoleSource, /api\/hellofresh\/account\/weeks/);
  assert.match(consoleSource, /api\/hellofresh\/account\/recipes/);
  assert.match(consoleSource, /Se innhold/);
  assert.match(consoleSource, /Skjul innhold/);
  assert.match(consoleSource, /Ingredienser/);
  assert.doesNotMatch(consoleSource, /detail\.steps|Fremgangsmåte/);
  assert.match(consoleSource, /Filtrer på type rett/);
  assert.match(consoleSource, /Kjøtt/);
  assert.match(consoleSource, /Vegetar/);
  assert.match(consoleSource, /aria-expanded/);
  assert.match(consoleSource, /selection_snapshot/);
  assert.doesNotMatch(consoleSource, /Send engangskobling|Kopier hele lenken|auth\/link\/|auth\/bootstrap|auth\/complete/);
  assert.doesNotMatch(consoleSource, /window\.open\(/);
  assert.match(consoleSource, /HelloFreshRecipeImage/);
  assert.match(consoleSource, /apiBase\(\).*recipe\.image_url/);
  assert.match(consoleSource, /fetchPriority=\{recipe\.selected_quantity\?"high":"auto"\}/);
  assert.match(apiSource, /HelloFreshNorwayClient/);
  assert.match(apiSource, /HelloFreshImageCache/);
  assert.match(apiSource, /respond_image/);
  assert.match(apiSource, /api\/hellofresh\/images\/\(\[0-9a-f\]\{64\}\)/);
  assert.match(apiSource, /features\["hellofresh"\]/);
  assert.match(apiSource, /account\/recipes\/\(\[0-9a-f\]\{24\}\)/);
  assert.match(deploySource, /local_api\/hellofresh_account\.py/);
  assert.match(deploySource, /local_api\/hellofresh_account_transport\.py/);
  assert.match(deploySource, /local_api\/hellofresh_images\.py/);
  assert.match(deploySource, /local_api\/hellofresh_norway\.py/);
  assert.match(deploySource, /prefetch_hellofresh_images\.py/);
  assert.match(deploySource, /--allow-empty-requirements/);
  assert.match(deploySource, /requirements-base\.txt/);
  assert.match(deploySource, /FAMILYBOT_ALLOW_PENDING_PORTAL_SCHEMA=1/);
  assert.match(deploySource, /dashboard_migration\.py --status/);
  assert.match(deploySource, /\.venv\/bin\/python/);
  assert.match(deploySource, /requirements\.txt/);
  assert.match(deploySource, /FAMILYBOT_NODE/);
  assert.match(deploySource, /FAMILYBOT_DEPLOY_BRANCH:-dev/);
  assert.match(deploySource, /command -v node/);
  assert.match(deploySource, /plistlib\.load/);
  assert.match(deploySource, /plistlib\.dumps/);
  assert.doesNotMatch(deploySource, /sed -e/);
  assert.match(supervisorSource, /FAMILYBOT_NODE/);
  assert.match(supervisorSource, /shutil\.which\("node"/);
  assert.doesNotMatch(supervisorSource, /\/opt\/homebrew\/bin\/node/);
  assert.match(portalPlist, /__FAMILYBOT_NODE__/);
  assert.match(helloFreshSource, /https:\/\/www\.hellofresh\.no/);
  assert.match(helloFreshSource, /systemCountry.*NO/);
  assert.match(helloFreshSource, /locale.*nb-NO/);
  assert.match(helloFreshSource, /MAX_HTML_BYTES/);
  assert.match(helloFreshSource, /ALLOWED_IMAGE_HOSTS/);
  assert.doesNotMatch(
    helloFreshSource,
    /HELLOFRESH_(?:EMAIL|PASSWORD)|(?:import|from)\s+(?:playwright|selenium)|["']Cookie["']\s*:/i,
  );
  assert.match(helloFreshAccountSource, /\/gw\/login/);
  assert.match(helloFreshAccountSource, /\/gw\/refresh/);
  assert.match(helloFreshAccountSource, /complete_login/);
  assert.match(helloFreshAccountSource, /challenge/);
  assert.match(helloFreshAccountSource, /hellofresh-no\.json/);
  assert.match(helloFreshAccountSource, /0o600/);
  assert.match(helloFreshAccountSource, /\/gw\/auth\/token/);
  assert.match(helloFreshAccountSource, /curl_cffi/);
  assert.match(helloFreshAccountSource, /impersonate="chrome"/);
  assert.match(helloFreshAccountSource, /verify=True/);
  assert.match(helloFreshAccountSource, /Sec-Fetch-Site/);
  assert.match(helloFreshAccountSource, /\/gw\/v1\/carts\//);
  assert.match(helloFreshAccountSource, /x-requested-by/);
  assert.match(helloFreshAccountSource, /_preserved_extras/);
  assert.match(helloFreshAccountSource, /_menu_snapshot/);
  assert.match(helloFreshAccountSource, /hasSeamlessDowngraded/);
  assert.match(helloFreshAccountSource, /_mutation_lock/);
  assert.match(helloFreshAccountSource, /PROVIDER_CONTRACT_VERSION = 1/);
  assert.match(helloFreshAccountSource, /validate_provider_path/);
  assert.doesNotMatch(helloFreshAccountSource, /passwordless|MAGIC_LINK/);
  assert.doesNotMatch(helloFreshAccountSource, /HELLOFRESH_PASSWORD|playwright|selenium/i);
  assert.match(helloFreshImageSource, /ALLOWED_CONTENT_TYPES/);
  assert.match(helloFreshImageSource, /MAX_IMAGE_BYTES = 6_000_000/);
  assert.match(helloFreshImageSource, /MAX_CACHE_BYTES = 256 \* 1024 \* 1024/);
  assert.match(helloFreshImageSource, /c_limit,f_auto,q_auto,w_960/);
  assert.match(helloFreshImageSource, /_safe_image_url/);
  assert.match(helloFreshImageSource, /stale beats empty/);
  assert.doesNotMatch(helloFreshImageSource, /parse_qs|query\.get\(["'](?:url|source)/i);
  assert.match(imagePlist, /ai\.familybot\.portal-images/);
  assert.match(imagePlist, /<integer>4<\/integer>/);
  assert.match(imagePlist, /<integer>45<\/integer>/);
  assert.match(odaSource, /recipe_search/);
  assert.match(odaSource, /get_liked_recipes/);
  assert.match(odaSource, /get_purchased_recipes/);
  assert.match(odaSource, /fromRecipePortions/);
  assert.match(dinnerSource, /familybot-oda-dinner/);
  assert.match(dinnerSource, /MAX_HISTORY_MESSAGES = 6/);
  assert.match(dinnerSource, /fallback to a direct Oda recipe search|_fallback/);
  assert.match(dinnerSource, /images\.oda\.com/);
  assert.match(dinnerSource, /MAX_RECIPE_HTML_BYTES/);
  assert.match(dinnerSource, /_allowed_recipe_url/);
  assert.match(dinnerSource, /application\/ld\+json/);
  assert.match(dinnerSource, /recipeIngredient/);
  assert.match(dinnerSource, /recipeInstructions/);
  assert.match(consoleSource, /function TransportCountdown/);
  assert.match(consoleSource, /VITE_FAMILYBOT_API_PORT/);
  assert.match(consoleSource, /data\.family\?\.timezone/);
  assert.match(consoleSource, /new Intl\.DateTimeFormat\(locale/);
  assert.match(consoleSource, /second:"2-digit"/);
  assert.match(consoleSource, /Klokken er nå:/);
  assert.match(consoleSource, /Synket fra FamilyBot/);
  assert.match(consoleSource, /hero-clock/);
  assert.doesNotMatch(consoleSource, /<p className="eyebrow">Hjemme<\/p><h2>FamilyBot<\/h2>/);
  assert.match(consoleSource, /God morgen/);
  assert.match(consoleSource, /God dag/);
  assert.match(consoleSource, /God ettermiddag/);
  assert.match(consoleSource, /God kveld/);
  const greetingSource = consoleSource.match(/function greetingForHour\(hour:number\)\{[^}]+\}/)?.[0];
  assert.ok(greetingSource);
  const greetingForHour = Function(`${greetingSource.replace("hour:number", "hour")}; return greetingForHour;`)();
  assert.equal(greetingForHour(7), "God morgen");
  assert.equal(greetingForHour(12), "God dag");
  assert.equal(greetingForHour(16), "God ettermiddag");
  assert.equal(greetingForHour(20), "God kveld");
  assert.equal(greetingForHour(2), "God kveld");
  assert.doesNotMatch(consoleSource, /Spør FamilyBot i Telegram/);
  assert.match(styles, /\.realtime-badge\{[^}]*white-space:nowrap/);
  assert.match(styles, /\.departure-countdown\{[^}]*white-space:nowrap/);
  assert.match(consoleSource, /setInterval\(\(\)=>setNow\(Date\.now\(\)\),1_000\)/);
  assert.match(consoleSource, /Neste mot sentrum|transport\.status/);
  assert.match(apiSource, /centre_quay_id/);
  assert.match(apiSource, /ET-Client-Name/);
  assert.doesNotMatch(consoleSource, /crypto\.randomUUID\(\)/);
  assert.match(apiSource, /0\.0\.0\.0/);
  assert.match(apiSource, /X-FamilyBot-Local-Token/);
  assert.match(apiSource, /X-FamilyBot-Parent-Token/);
  assert.match(apiSource, /archived_at=datetime\('now'\)/);
  assert.match(apiSource, /chore_cycles/);
  assert.match(apiSource, /reset_child/);
  assert.match(apiSource, /LANES = \{"todo", "inprogress", "onhold", "done"\}/);
  assert.match(apiSource, /api\/kanban/);
  assert.match(apiSource, /api\/oda\/oauth\/callback/);
  assert.match(apiSource, /api\/oda\/search/);
  assert.match(apiSource, /api\/oda\/cart/);
  assert.doesNotMatch(apiSource, /api\/chat|chat_slot|chat_answer/);
  assert.match(apiSource, /api\/hellofresh\/menu/);
  assert.match(apiSource, /api\/hellofresh\/auth\/login/);
  assert.doesNotMatch(apiSource, /api\/hellofresh\/auth\/(?:bootstrap|complete|link)/);
  assert.doesNotMatch(apiSource, /api\/hellofresh\/auth\/callback/);
  assert.match(apiSource, /api\/hellofresh\/account\/menu/);
  assert.match(odaSource, /https:\/\/oda\.com\/mcp/);
  assert.match(odaSource, /FAMILYBOT_WORKSPACE/);
  assert.match(odaSource, /credentials\/oda-mcp\.json/);
  assert.match(odaSource, /product_search/);
  assert.match(odaSource, /likely_to_buy/);
  assert.match(odaSource, /manipulate_cart/);
  assert.match(odaSource, /clear_cart/);
  assert.match(odaSource, /code_challenge_method/);
  assert.match(odaSource, /Mcp-Session-Id/);
  assert.doesNotMatch(odaSource, /OpenAI|openclaw agent|tools\/call.*payload/i);
  assert.match(apiSource, /NOT EXISTS \(SELECT 1 FROM family_chore_meta/);
  assert.match(apiSource, /weekly_achievement_cycles/);
  assert.match(apiSource, /weekly_surprise_levels/);
  assert.match(apiSource, /full_tabs/);
  assert.match(apiSource, /annual_chore_counts/);
  assert.match(apiSource, /status.*pending.*awarded/);
  assert.doesNotMatch(apiSource, /SELECT \*/i);
});
