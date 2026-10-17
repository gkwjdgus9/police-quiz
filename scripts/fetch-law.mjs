// 국가법령정보센터 공동활용 Open API에서 현행 조문을 받아 law-data.json으로 저장합니다.
// 사용법: LAW_OC=<법령정보센터 Open API 인증 아이디> node scripts/fetch-law.mjs
// LAW_OC는 https://open.law.go.kr 에서 신청하는 OC 값(보통 이메일 아이디 부분)입니다.
import { writeFileSync } from 'node:fs';

const OC = process.env.LAW_OC;
if (!OC) { console.error('LAW_OC 환경변수가 없습니다.'); process.exit(1); }

// 이 도구가 요약한 법령과 조문. 조문번호는 "제3조", "제5조의3" 형식.
const TARGETS = [
  { name: '교통사고처리특례법', articles: ['제3조', '제4조'] },
  { name: '특정범죄가중처벌등에관한법률', articles: ['제5조의3', '제5조의11', '제5조의13'] },
  { name: '도로교통법', articles: ['제27조', '제54조', '제148조', '제151조'] },
];

const asArray = v => (v == null ? [] : Array.isArray(v) ? v : [v]);
const clean = s => String(s ?? '').replace(/\s+\n/g, '\n').trim();

function articleText(unit) {
  // 조문내용 + 항/호/목을 평문으로 합침. API 응답 구조가 달라도 가능한 한 복원.
  const parts = [clean(unit['조문내용'])];
  for (const h of asArray(unit['항'])) {
    const hText = clean(h['항내용']);
    if (hText) parts.push(hText);
    for (const ho of asArray(h['호'])) {
      const hoText = clean(ho['호내용']);
      if (hoText) parts.push('  ' + hoText);
      for (const mok of asArray(ho['목'])) {
        const m = clean(mok['목내용']);
        if (m) parts.push('    ' + m);
      }
    }
  }
  return parts.filter(Boolean).join('\n');
}

async function fetchLaw(name) {
  const url = `https://www.law.go.kr/DRF/lawService.do?OC=${encodeURIComponent(OC)}&target=law&LM=${encodeURIComponent(name)}&type=JSON`;
  const res = await fetch(url, { headers: { 'User-Agent': 'police-quiz traffic-check law sync' } });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error(`${name}: JSON이 아닌 응답 (인증 아이디 또는 법령명 확인)\n${text.slice(0, 300)}`); }
  const law = data['법령'] ?? data;
  const info = law['기본정보'] ?? {};
  const units = asArray(law['조문']?.['조문단위']);
  if (!units.length) throw new Error(`${name}: 조문단위가 비어 있음`);
  return { info, units };
}

const out = { fetchedAt: new Date().toISOString(), source: 'https://www.law.go.kr (국가법령정보센터 Open API)', laws: [] };
let failed = false;
for (const t of TARGETS) {
  try {
    const { info, units } = await fetchLaw(t.name);
    const articles = t.articles.map(no => {
      const n = no.replace(/^제|조$/g, '').replace('조의', '의'); // "제5조의3" -> "5의3"
      const unit = units.find(u => {
        const num = String(u['조문번호'] ?? '');
        const sub = u['조문가지번호'] ? `${num}의${u['조문가지번호']}` : num;
        return (sub === n || num === n) && (u['조문여부'] == null || u['조문여부'] === '조문');
      });
      return unit
        ? { no, title: clean(unit['조문제목']), text: articleText(unit) }
        : { no, title: '', text: '(해당 조문을 응답에서 찾지 못했습니다)' };
    });
    out.laws.push({
      name: info['법령명_한글'] ?? t.name,
      effective: String(info['시행일자'] ?? ''),
      promulgated: String(info['공포일자'] ?? ''),
      number: info['공포번호'] ?? '',
      articles,
    });
    console.log(`${t.name}: 시행 ${info['시행일자']} · ${articles.length}개 조문`);
  } catch (e) {
    failed = true;
    console.error(String(e.message || e));
  }
}
if (!out.laws.length) { console.error('가져온 법령이 없어 파일을 쓰지 않습니다.'); process.exit(1); }
writeFileSync('law-data.json', JSON.stringify(out, null, 2) + '\n');
console.log(`law-data.json 저장 (${out.laws.length}개 법령)` + (failed ? ' · 일부 실패' : ''));
