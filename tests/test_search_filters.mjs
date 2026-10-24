import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const code = await readFile(new URL('../web/y/search-filters.js', import.meta.url), 'utf8');
const {viewLimit, refineSearch, searchSourceSort} = await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const items = [
 {videoId:'a',type:'video',viewCount:1000,published:300},
 {videoId:'b',type:'video',viewCount:null,published:0},
 {videoId:'c',type:'video',viewCount:0,published:200},
 {videoId:'d',type:'video',viewCount:10,published:100},
 {videoId:'e',type:'video',published:null},
 {type:'channel',authorId:'channel',viewCount:1,published:1},
];
const ids = x => x.map(v=>v.videoId);
assert.deepEqual(ids(refineSearch(items,{sort:'views_asc'})),['c','d','a','b','e']);
assert.deepEqual(ids(refineSearch(items,{sort:'date_asc'})),['d','c','a','b','e']);
assert.deepEqual(ids(refineSearch(items,{sort:'views_asc',min_views:'0',max_views:'10'})),['c','d']);
assert.deepEqual(ids(refineSearch(items,{sort:'relevance',min_views:'10',max_views:'1000'})),['a','d']);
assert.equal(refineSearch(items,{sort:'relevance',max_views:'0'}).length,1);
assert.equal(refineSearch(items,{sort:'relevance',min_views:'10',max_views:'2'}).length,0);
assert.equal(refineSearch(items,{sort:'relevance'}).length,6);
for (const x of [null,'','-1','1.5','NaN','Infinity','1e3','9007199254740992','<script>']) assert.equal(viewLimit(x),'');
assert.equal(viewLimit('0'),'0'); assert.equal(viewLimit('0010'),'10');
assert.equal(viewLimit('9007199254740991'),'9007199254740991');
assert.equal(searchSourceSort('views_asc'),'relevance');
assert.equal(searchSourceSort('date_asc'),'relevance');
assert.equal(searchSourceSort('views'),'views');
assert.deepEqual(ids(items).slice(0,5),['a','b','c','d','e']);
console.log('PASS: ascending views/dates, unknown values, zero, inclusive ranges, mixed types, URL bounds and source sort');
