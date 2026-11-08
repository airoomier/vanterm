// kullanım: node purge.js <liste.json>   liste: [{css: dosya, html: dosya, out: dosya}, ...]
const { PurgeCSS } = require('purgecss');
const fs = require('fs');
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const safelist = {
  standard: [/^owl-/, /^mfp-/, /^rs-/, /^rev/, /^tp-/, /sticky/, /fixed/, /^is-/, /^active$/, /^open$/, /^show$/, /^in$/, /^collapse/, /^cli/, /^cookie/, /^wpml/, /^flex-/, /^slides$/, /^vt-/, /^cspt-sticky/, /^menu-/, /^sub-menu/, /^current/, /^focus/, /^hover/, /^js-/, /^loaded/, /^lazy/, /^animated/, /^fade/],
  deep: [/owl-/, /mfp-/, /rs-/, /sticky/],
  greedy: [/owl/, /mfp/, /rs-/, /font-size/, /style\*=/],
};
(async () => {
  for (const j of jobs) {
    const content = Array.isArray(j.html) ? j.html : [j.html];
    const res = await new PurgeCSS().purge({ content, css: [j.css], safelist, dynamicAttributes: ['style'], fontFace: false, keyframes: false, variables: false, rejected: false });
    fs.writeFileSync(j.out, res[0].css);
  }
  console.log('purge tamam', jobs.length);
})().catch(e => { console.error(e); process.exit(1); });
