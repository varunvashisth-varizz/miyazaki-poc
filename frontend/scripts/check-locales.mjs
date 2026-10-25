import fs from 'node:fs';
const s=fs.readFileSync(new URL('../src/i18n.ts',import.meta.url),'utf8');
const keys=[...s.matchAll(/(?:^|,)\s*([a-zA-Z_]+):\['([^']*(?:’[^']*)*)','([^']*)'\]/g)];
if(keys.length<150)throw new Error('Localisation resource parse failed or missing bilingual keys');
for(const [,key,en,ja]of keys){if(!en.trim()||!ja.trim())throw new Error('Missing locale value: '+key)}
console.log(`PASS: ${keys.length} bilingual resource pairs. Both locale maps derive from the same keys.`);
