// test_prefy_complete_coverage.mjs — Prefy Complete Product Knowledge phase.
//
// Proves, structurally, that NO major registered navigation path in any
// of the three portals can resolve to Prefy's UNKNOWN_CONTEXT fallback
// during normal use. Complements test_prefy_real_page.mjs (which proves
// this behaviorally, via real clicks, for the voter registration flow
// specifically that human QA flagged) by covering the other two portals
// and every literal/ternary/map-based setContext call site source-wide.
//
// Run with: node test_prefy_complete_coverage.mjs

import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const Content = require('./prefy-content.js');

let passed = 0, failed = 0;
const failures = [];
function assertEqual(actual, expected, msg) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) passed++; else { failed++; failures.push(`${msg}: expected ${e}, got ${a}`); }
}
function assertTrue(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }

const voter = fs.readFileSync('voter_portal.html', 'utf-8');
const marketer = fs.readFileSync('marketer_portal.html', 'utf-8');
const organizer = fs.readFileSync('preferendum_organizer.html', 'utf-8');
const REGISTERED = new Set(Content.listContextKeys());

// ═══════════════════════════════════════════════════════════════════════
// 1. Every literal Prefy.setContext('...') call site, in every portal,
//    resolves to a REAL registered context — never a typo, never
//    (accidentally) the _unknown fallback key itself.
// ═══════════════════════════════════════════════════════════════════════
function literalSetContextKeys(src) {
  const re = /Prefy\.setContext\(\s*'([a-zA-Z0-9_.]+)'/g;
  const found = new Set();
  let m;
  while ((m = re.exec(src))) found.add(m[1]);
  return found;
}
[['voter_portal.html', voter], ['marketer_portal.html', marketer], ['preferendum_organizer.html', organizer]].forEach(([name, src]) => {
  const keys = literalSetContextKeys(src);
  assertTrue(keys.size > 0, `${name} has at least one literal Prefy.setContext(...) call site`);
  keys.forEach((k) => {
    assertTrue(REGISTERED.has(k), `${name}'s literal setContext('${k}') resolves to a REAL registered context`);
    assertTrue(k !== Content.UNKNOWN_CONTEXT_KEY, `${name}'s literal setContext('${k}') never deliberately targets the unknown-context fallback`);
  });
});

// ═══════════════════════════════════════════════════════════════════════
// 2. Ternary-based tab switches (ambiguous for a simple regex) — checked
//    explicitly by name, since these are exactly the choke points this
//    phase fixed.
// ═══════════════════════════════════════════════════════════════════════
const ternaryChecks = [
  [voter, 'voter_portal.html', "tab === 'register' ? 'voter.register.overview' : 'voter.auth.login'"],
  [marketer, 'marketer_portal.html', "tab === 'register' ? 'marketer.auth.register' : 'marketer.auth.login'"],
  [organizer, 'preferendum_organizer.html', "tab === 'register' ? 'organizer.auth.register' : 'organizer.auth.login'"],
];
ternaryChecks.forEach(([src, name, needle]) => {
  assertTrue(src.includes(needle), `${name}'s auth-tab switch resolves BOTH tabs to real, distinct, registered contexts`);
});
[
  ['voter.register.overview', 'voter.auth.login'],
  ['marketer.auth.register', 'marketer.auth.login'],
  ['organizer.auth.register', 'organizer.auth.login'],
].forEach(([a, b]) => {
  assertTrue(REGISTERED.has(a) && REGISTERED.has(b), `both ternary branches (${a}, ${b}) are real registered contexts`);
});

// ═══════════════════════════════════════════════════════════════════════
// 3. Map-based wiring (fieldContextMap, _PREFY_TAB_CONTEXT,
//    _PREFY_PANEL_CONTEXT) — every VALUE must be a real registered
//    context, never a typo that would silently fall back to unknown.
// ═══════════════════════════════════════════════════════════════════════
function mapValues(src, varName) {
  const start = src.indexOf(`${varName} = {`);
  if (start === -1) return null;
  const end = src.indexOf('}', start);
  const body = src.slice(start, end);
  const re = /'([a-zA-Z0-9_.]+)'(?=\s*[,}])/g;
  const values = [];
  let m;
  while ((m = re.exec(body))) values.push(m[1]);
  return values;
}

const voterFieldMapStart = voter.indexOf('var fieldContextMap = {');
const voterFieldMapEnd = voter.indexOf('};', voterFieldMapStart);
const voterFieldMapBody = voter.slice(voterFieldMapStart, voterFieldMapEnd);
const voterFieldMapValues = [...voterFieldMapBody.matchAll(/:\s*'([a-zA-Z0-9_.]+)'/g)].map((m) => m[1]);
assertTrue(voterFieldMapValues.length >= 13, 'voter_portal.html\'s fieldContextMap covers at least the 13 known real fields (name/pass/rut/gender/country/commune/dob/occupation/company_size/email/phone/selfie/document)');
voterFieldMapValues.forEach((k) => assertTrue(REGISTERED.has(k), `voter fieldContextMap value '${k}' is a real registered context`));

const orgFieldMapStart = organizer.indexOf('var fieldContextMap = {');
const orgFieldMapEnd = organizer.indexOf('};', orgFieldMapStart);
const orgFieldMapValues = [...organizer.slice(orgFieldMapStart, orgFieldMapEnd).matchAll(/:\s*'([a-zA-Z0-9_.]+)'/g)].map((m) => m[1]);
assertTrue(orgFieldMapValues.length > 0, 'preferendum_organizer.html has a non-empty fieldContextMap');
orgFieldMapValues.forEach((k) => assertTrue(REGISTERED.has(k), `organizer fieldContextMap value '${k}' is a real registered context`));

const tabContextStart = voter.indexOf('_PREFY_TAB_CONTEXT = {');
const tabContextEnd = voter.indexOf('};', tabContextStart);
const tabContextValues = [...voter.slice(tabContextStart, tabContextEnd).matchAll(/:\s*'([a-zA-Z0-9_.]+)'/g)].map((m) => m[1]);
assertEqual(tabContextValues.sort(), ['voter.consultations', 'voter.opinion', 'voter.profile', 'voter.results', 'voter.voting_section'].sort(), 'voter\'s bottom-nav tab map covers exactly the 5 real tabs, each with a real context');

const panelContextStart = marketer.indexOf('_PREFY_PANEL_CONTEXT = {');
const panelContextEnd = marketer.indexOf('};', panelContextStart);
const panelContextValues = [...marketer.slice(panelContextStart, panelContextEnd).matchAll(/:\s*'([a-zA-Z0-9_.]+)'/g)].map((m) => m[1]);
assertEqual(panelContextValues.sort(), ['marketer.campaigns.overview', 'marketer.panel.credits', 'marketer.campaign.create', 'marketer.panel.overview'].sort(), "marketer's panel map covers exactly the 4 real panels, each with a real context");

// Granular campaign-form field map (Prefy Campaigns Deep-Dive Revision) —
// same shape/validation as voter's own fieldContextMap above.
const campaignFieldMapStart = marketer.indexOf('var campaignFieldContextMap = {');
const campaignFieldMapEnd = marketer.indexOf('};', campaignFieldMapStart);
const campaignFieldMapValues = [...marketer.slice(campaignFieldMapStart, campaignFieldMapEnd).matchAll(/:\s*'([a-zA-Z0-9_.]+)'/g)].map((m) => m[1]);
assertTrue(campaignFieldMapValues.length >= 15, "marketer_portal.html's campaignFieldContextMap covers at least the 15 real campaign-form fields/sections");
campaignFieldMapValues.forEach((k) => assertTrue(REGISTERED.has(k), `campaign field map value '${k}' is a real registered context`));

// ═══════════════════════════════════════════════════════════════════════
// 4. The explicit SCREEN → CONTEXT coverage map this phase audited
//    (task §2/§12) — every named screen has a real, non-unknown context.
// ═══════════════════════════════════════════════════════════════════════
const COVERAGE_MAP = {
  voter: {
    login: 'voter.auth.login',
    registration_overview: 'voter.register.overview',
    'registration:name': 'voter.register.name',
    'registration:password': 'voter.register.password',
    'registration:national_id': 'voter.register.national_id',
    'registration:gender': 'voter.register.gender',
    'registration:country': 'voter.register.country',
    'registration:commune': 'voter.register.commune',
    'registration:dob': 'voter.register.dob',
    'registration:occupation': 'voter.register.occupation',
    'registration:company_size': 'voter.register.company_size',
    'registration:email': 'voter.register.email',
    'registration:phone': 'voter.register.phone',
    verification_overview: 'voter.verify.overview',
    'verification:selfie': 'voter.verify.selfie',
    'verification:document': 'voter.verify.document',
    home_consultation_type_choice: 'voter.home_selection',
    home_welcome_or_list: 'voter.welcome', // (or voter.consultations on repeat visits)
    consultation_list: 'voter.consultations',
    consultation_detail: 'voter.consultation.detail',
    voting: 'voter.voting_section',
    pre_vote_attention: 'voter.vote.before_submit',
    vote_success: 'voter.vote.success',
    results: 'voter.results',
    comments: 'voter.opinion',
    profile: 'voter.profile',
    logout: 'voter.logout',
    missing_field: 'voter.missing_field',
    generic_error: 'voter.error.generic',
  },
  organizer: {
    login: 'organizer.auth.login',
    register: 'organizer.auth.register',
    dashboard: 'organizer.home',
    create_consultation: 'organizer.create',
    targeting_eligibility: 'organizer.create.targeting',
    results: 'organizer.results',
    missing_field: 'organizer.missing_field',
    logout: 'organizer.logout',
  },
  marketer: {
    login: 'marketer.auth.login',
    register: 'marketer.auth.register',
    dashboard_overview: 'marketer.panel.overview',
    credits: 'marketer.panel.credits',
    campaigns: 'marketer.campaigns.overview',
    campaign_toggle_active_paused: 'marketer.campaign.active',
    new_campaign: 'marketer.campaign.create',
    'new_campaign:details': 'marketer.campaign.details',
    'new_campaign:geography': 'marketer.campaign.geography',
    'new_campaign:socioeconomic': 'marketer.campaign.socioeconomic',
    'new_campaign:demographics': 'marketer.campaign.demographics',
    'new_campaign:company_size': 'marketer.campaign.company_size',
    'new_campaign:occupation': 'marketer.campaign.occupation',
    'new_campaign:brand_safety': 'marketer.campaign.brand_safety',
    'new_campaign:credits': 'marketer.campaign.credits',
    campaign_launch: 'marketer.campaign.review',
    campaign_results: 'marketer.campaign.results',
    missing_field: 'marketer.missing_field',
    logout: 'marketer.logout',
  },
};
Object.keys(COVERAGE_MAP).forEach((portal) => {
  Object.keys(COVERAGE_MAP[portal]).forEach((screen) => {
    const key = COVERAGE_MAP[portal][screen];
    assertTrue(REGISTERED.has(key), `[${portal}] screen "${screen}" maps to a real registered context (${key})`);
    assertTrue(key !== Content.UNKNOWN_CONTEXT_KEY, `[${portal}] screen "${screen}" is never mapped to the unknown fallback`);
  });
});
const totalScreens = Object.values(COVERAGE_MAP).reduce((n, p) => n + Object.keys(p).length, 0);
assertTrue(totalScreens >= 43, `the coverage map documents at least 43 distinct screens/fields across all three portals (got ${totalScreens})`);

// ═══════════════════════════════════════════════════════════════════════
// 5. Every context every one of the three coverage maps names actually
//    renders REAL (non-fallback) text in all 30 languages — the final
//    proof that none of them silently degrade to the unknown copy.
// ═══════════════════════════════════════════════════════════════════════
const CANONICAL_30 = Object.keys(Content.STRINGS);
const allMappedKeys = new Set();
Object.values(COVERAGE_MAP).forEach((p) => Object.values(p).forEach((k) => allMappedKeys.add(k)));
allMappedKeys.forEach((key) => {
  CANONICAL_30.forEach((lang) => {
    const rendered = Content.render(key, lang);
    assertEqual(rendered.key, key, `${key}/${lang} resolves to itself, never silently redirecting to _unknown`);
    assertTrue(!!rendered.title && !!rendered.body, `${key}/${lang} has non-empty title and body`);
  });
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  console.log('\nFAILURES:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
} else {
  process.exit(0);
}
