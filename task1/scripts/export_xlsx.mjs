/** Optional XLSX export using the bundled @oai/artifact-tool runtime.
 * Run from task1: node src/export_xlsx.mjs --input-dir data/processed
 * The Python preprocessing output remains authoritative and lossless.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const args = process.argv.slice(2);
let inputDir = 'data/processed';
let preview = true;
let renderWorker = false;
for (let index = 0; index < args.length; index += 1) {
  if (args[index] === '--input-dir') inputDir = args[++index];
  else if (args[index] === '--no-preview') preview = false;
  else if (args[index] === '--render-worker') renderWorker = true;
  else throw new Error(`Unknown argument: ${args[index]}`);
}
inputDir = path.resolve(inputDir);
const qaDir = path.join(inputDir, '..', '..', 'qa', 'xlsx');
await fs.mkdir(qaDir, { recursive: true });
const inputText = await fs.readFile(path.join(inputDir, 'dataset_clean.jsonl'), 'utf8');
const rows = inputText.replace(/^\uFEFF/, '').split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line));
const qualityPath = path.join(inputDir, 'quality_report.json');
const quality = JSON.parse(await fs.readFile(qualityPath, 'utf8'));
const fields = quality.dataset_fields || [...new Set(rows.flatMap(row => Object.keys(row)))];
if (!fields.length) throw new Error('No dataset fields found. Run src/preprocess.py first.');
if (quality.accepted_records !== rows.length) throw new Error('JSONL row count does not match quality_report.json.');

const descriptions = {
  record_id: '采集记录唯一编号', scenic_area: '景区名称', source_platform: '来源平台或官方机构',
  source_url: '采集时原始文章地址', title: '来源文章标题', text_type: 'official_route 官方路线 / travelogue 游客游记',
  collected_at: 'Excel 数值日期，以 UTC 显示；CSV/JSONL 保留原始 ISO 时间和时区', raw_content: '提取范围内未清洗原始正文；超过 Excel 上限时引用完整旁存文本',
  raw_format: 'html / text', extraction_selector: '正文定位选择器或浏览器提取说明', raw_file: '原始采集快照相对路径',
  content_scope: '正文范围；标明全文或路线节选', author: '来源署名，原文未提供则留空', published_at: '来源发布时间；不以采集时间替代',
  clean_content: '保留原文语义的清洗正文；超过 Excel 上限时引用完整旁存文本',
  raw_char_count: '原始正文字符数；HTML 含标签', extracted_char_count: '去除 HTML 区域后的文本字符数',
  clean_char_count: '清洗后字符数，含空白', clean_nonspace_char_count: '清洗后非空白字符数',
  retention_ratio: '清洗后字符数 / HTML 提取文本字符数', canonical_source_url: '删除跟踪参数与片段后的去重地址',
  content_sha256: '清洗正文 SHA-256', cleaning_counts: '规则命中统计，JSON 格式', quality_flags: '人工复核警告，JSON 格式',
};
const toScalar = value => value === null || value === undefined ? ''
  : typeof value === 'object' ? JSON.stringify(value) : value;
const literal = value => typeof value === 'string' && value.startsWith('=') ? `'${value}` : value;
const charCount = value => [...value].length;
const sha256 = value => createHash('sha256').update(value, 'utf8').digest('hex');
const externalized = quality.xlsx_long_text_externalization || [];
const externalMap = new Map(externalized.map(entry => [`${entry.record_id}\u0000${entry.field}`, entry]));
const matrix = [];
for (const [index, row] of rows.entries()) {
  const values = [];
  for (const field of fields) {
    let value = toScalar(row[field]);
    if (field === 'collected_at' && typeof value === 'string' && value && !Number.isNaN(Date.parse(value))) value = new Date(value);
    if (typeof value === 'string' && value.length > 32767) {
      let entry = externalMap.get(`${row.record_id}\u0000${field}`);
      if (!entry) {
        const safeId = String(row.record_id).replace(/[^A-Za-z0-9._-]+/g, '_') || `row${index + 2}`;
        const relative = `long_text/${String(index + 2).padStart(4, '0')}_${safeId}_${field}.txt`;
        await fs.mkdir(path.join(inputDir, 'long_text'), { recursive: true });
        await fs.writeFile(path.join(inputDir, relative), value, 'utf8');
        entry = { record_id: row.record_id, field, characters: charCount(value), path: relative, sha256: sha256(value) };
        externalized.push(entry);
        externalMap.set(`${row.record_id}\u0000${field}`, entry);
      } else {
        // Refuse stale sidecars rather than writing an incorrect reference.
        const fullText = await fs.readFile(path.join(inputDir, entry.path), 'utf8');
        if (fullText !== value) throw new Error(`Stale long-text sidecar: ${entry.path}`);
      }
      value = `[完整文本外置] ${entry.characters} 字符，见 ${entry.path}。CSV/JSONL 保留全文。`;
    }
    values.push(literal(value));
  }
  matrix.push(values);
}

const workbook = Workbook.create();
const summary = workbook.worksheets.add('数据概览');
const data = workbook.worksheets.add('清洗数据');
const dictionary = workbook.worksheets.add('字段说明');
const font = 'Microsoft YaHei';
const header = '#23475E';
const pale = '#F1F5F8';
function baseStyle(sheet, range) {
  sheet.showGridLines = false;
  range.format.font = { name: font, size: 10, color: '#18252F' };
  range.format.verticalAlignment = 'center';
  range.format.rowHeight = 26;
}
function headerStyle(range) {
  range.format.fill = header;
  range.format.font = { name: font, size: 10, bold: true, color: '#FFFFFF' };
  range.format.horizontalAlignment = 'center';
  range.format.verticalAlignment = 'center';
  range.format.wrapText = true;
  range.format.rowHeight = 36;
  range.format.borders = { bottom: { style: 'thin', color: '#D9D9D9' } };
}
const rowCount = rows.length + 1;
data.getRangeByIndexes(0, 0, 1, fields.length).values = [fields];
if (rows.length) data.getRangeByIndexes(1, 0, rows.length, fields.length).values = matrix;
baseStyle(data, data.getRangeByIndexes(0, 0, rowCount, fields.length));
headerStyle(data.getRangeByIndexes(0, 0, 1, fields.length));
for (let index = 1; index < rowCount; index += 1) {
  if (index % 2 === 0) data.getRangeByIndexes(index, 0, 1, fields.length).format.fill = pale;
}
for (const [index, field] of fields.entries()) {
  const column = data.getRangeByIndexes(0, index, rowCount, 1);
  column.format.columnWidth = ['raw_content', 'clean_content'].includes(field) ? 75
    : field === 'title' ? 52 : /url|selector|scope|file|sha256|counts|flags/.test(field) ? 40
    : /at$/.test(field) ? 30 : 22;
  if (/_count$/.test(field)) column.setNumberFormat('#,##0');
  else if (field === 'retention_ratio') column.setNumberFormat('0.0%');
  else if (field === 'collected_at') column.setNumberFormat('yyyy-mm-dd hh:mm:ss "UTC"');
  else if (field === 'published_at') column.setNumberFormat('yyyy-mm-dd');
  else column.setNumberFormat('@');
  if (['source_url', 'title', 'canonical_source_url', 'raw_file', 'extraction_selector', 'content_scope', 'quality_flags', 'author', 'published_at'].includes(field)) {
    column.format.wrapText = true;
  }
}
if (rows.length) data.getRangeByIndexes(1, 0, rows.length, Math.min(7, fields.length)).format.autofitRows();
// Long article cells retain their complete values or explicit sidecar references.
// Normal table rows show the opening line; select a cell to read its full value.
data.freezePanes.freezeRows(1);
data.freezePanes.freezeColumns(2);
const table = data.tables.add(data.getRangeByIndexes(0, 0, rowCount, fields.length), true, 'ScenicArticles');
table.showFilterButton = true;
data.tabColor = '#8CA3B2';

const scenicColumn = fields.indexOf('scenic_area');
const typeColumn = fields.indexOf('text_type');
function columnName(index) {
  let result = '';
  for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) result = String.fromCharCode(65 + (value - 1) % 26) + result;
  return result;
}
if (scenicColumn < 0 || typeColumn < 0) throw new Error('Required scenic_area/text_type columns missing.');
const scenicRange = `'清洗数据'!$${columnName(scenicColumn)}$2:$${columnName(scenicColumn)}$${Math.max(2, rowCount)}`;
const typeRange = `'清洗数据'!$${columnName(typeColumn)}$2:$${columnName(typeColumn)}$${Math.max(2, rowCount)}`;
summary.getRange('A2').values = [['景区指南采集数据概览']];
summary.getRange('A4:F4').values = [['景区', '官方路线', '游客游记', '合计', '达到 1 加 5 目标', '达到 1 加 3 最低标准']];
summary.getRange('A5:A7').values = [['黄山'], ['九寨沟'], ['颐和园']];
for (let row = 5; row <= 7; row += 1) {
  summary.getRange(`B${row}:F${row}`).formulas = [[
    `=COUNTIFS(${scenicRange},A${row},${typeRange},"official_route")`,
    `=COUNTIFS(${scenicRange},A${row},${typeRange},"travelogue")`,
    `=SUM(B${row}:C${row})`,
    `=IF(AND(B${row}>=1,C${row}>=5),"达到","未达到")`,
    `=IF(AND(B${row}>=1,C${row}>=3),"达到","未达到")`,
  ]];
}
summary.getRange('A8').values = [['合计']];
summary.getRange('B8:D8').formulas = [['=SUM(B5:B7)', '=SUM(C5:C7)', '=SUM(D5:D7)']];
summary.getRange('A10:B14').values = [
  ['输入记录数', quality.input_records], ['保留记录数', quality.accepted_records],
  ['拒收记录数', quality.rejected_records], ['近重复警告对数', quality.near_duplicate_pairs.length],
  ['长文本旁存数量', externalized.length],
];
summary.getRange('A16').values = [['长正文请在单元格编辑栏查看。超过 Excel 长度上限时，单元格引用完整旁存文本。']];
summary.getRange('A17').values = [['CSV 与 JSONL 始终保留全文。来源地址、正文范围与复核警告见清洗数据表。']];
summary.getRange('A18').values = [['采集时间以 UTC 显示。CSV 与 JSONL 保留原始 ISO 时间及其时区。']];
baseStyle(summary, summary.getRange('A1:F18'));
summary.getRange('A2').format.font = { name: font, size: 14, bold: true, color: '#000000' };
summary.getRange('A3:F3').format.borders = { bottom: { style: 'thin', color: '#AABAC4' } };
headerStyle(summary.getRange('A4:F4'));
summary.getRange('A5:F8').format.rowHeight = 30;
summary.getRange('B5:D14').setNumberFormat('#,##0');
summary.getRange('B5:D14').format.horizontalAlignment = 'right';
summary.getRange('E5:F7').format.horizontalAlignment = 'center';
summary.getRange('A8:D8').format.font = { name: font, size: 10, bold: true };
summary.getRange('A8:D8').format.borders = { top: { style: 'thin', color: '#AABAC4' } };
summary.getRange('A5:F5').format.fill = pale;
summary.getRange('A7:F7').format.fill = pale;
summary.getRange('A1:A18').format.columnWidth = 25;
summary.getRange('B1:D18').format.columnWidth = 17;
summary.getRange('E1:F18').format.columnWidth = 27;
summary.getRange('A16:A18').format.font = { name: font, size: 10, color: '#536873' };
summary.tabColor = header;

dictionary.getRangeByIndexes(0, 0, fields.length + 1, 2).values = [
  ['字段', '说明'], ...fields.map(field => [field, descriptions[field] || '采集阶段提供的附加字段，原样保留']),
];
baseStyle(dictionary, dictionary.getRangeByIndexes(0, 0, fields.length + 1, 2));
headerStyle(dictionary.getRange('A1:B1'));
dictionary.getRangeByIndexes(0, 0, fields.length + 1, 1).format.columnWidth = 39;
dictionary.getRangeByIndexes(0, 1, fields.length + 1, 1).format.columnWidth = 92;
dictionary.freezePanes.freezeRows(1);

workbook.recalculate();
const summaryValues = summary.getRange('A5:D8').values;
for (const [index, area] of ['黄山', '九寨沟', '颐和园'].entries()) {
  const expected = quality.coverage_by_scenic_area[area];
  const got = summaryValues[index];
  if (got[1] !== expected.official_route || got[2] !== expected.travelogue || got[3] !== expected.total) {
    throw new Error(`Summary mismatch for ${area}: ${JSON.stringify(got)}`);
  }
}
const inspected = await workbook.inspect({ kind: 'table', range: '数据概览!A4:F8', include: 'values,formulas', tableMaxRows: 6, tableMaxCols: 6, maxChars: 5000 });
await fs.writeFile(path.join(qaDir, 'summary_inspect.ndjson'), inspected.ndjson, 'utf8');
const errors = await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 50 }, summary: 'final formula error scan', maxChars: 3000 });
await fs.writeFile(path.join(qaDir, 'formula_errors.ndjson'), errors.ndjson, 'utf8');
if (renderWorker) {
  for (const [sheetName, range, outputName] of [
    ['数据概览', 'A1:F19', 'summary.png'], ['清洗数据', 'A1:G5', 'data.png'], ['字段说明', 'A1:B15', 'dictionary.png'],
  ]) {
    const blob = await workbook.render({ sheetName, range, scale: 1.4, format: 'png' });
    await fs.writeFile(path.join(qaDir, outputName), new Uint8Array(await blob.arrayBuffer()));
  }
  await fs.writeFile(path.join(qaDir, 'preview_manifest.json'), JSON.stringify({
    source_sha256: sha256(inputText), files: ['summary.png', 'data.png', 'dictionary.png'],
  }, null, 2), 'utf8');
  process.exit(0);
}
const outputPath = path.join(inputDir, 'dataset_clean.xlsx');
const file = await SpreadsheetFile.exportXlsx(workbook);
await file.save(outputPath);
quality.xlsx_long_text_externalization = externalized;
quality.xlsx_authoring = { engine: '@oai/artifact-tool', command: 'node src/export_xlsx.mjs --input-dir data/processed', status: 'exported', record_count: rows.length };
quality.output_files.xlsx = 'dataset_clean.xlsx';
await fs.writeFile(qualityPath, JSON.stringify(quality, null, 2) + '\n', 'utf8');
if (preview) {
  // Keep native rasterization in a child process. On some Windows builds the
  // renderer terminates during native cleanup after writing valid PNG files.
  // This must not damage or fail the independent XLSX export.
  const worker = spawnSync(process.execPath, [fileURLToPath(import.meta.url), '--input-dir', inputDir, '--render-worker'], { encoding: 'utf8' });
  const manifest = JSON.parse(await fs.readFile(path.join(qaDir, 'preview_manifest.json'), 'utf8'));
  if (manifest.source_sha256 !== sha256(inputText)) throw new Error('Preview source digest mismatch.');
  for (const name of manifest.files) {
    const bytes = await fs.readFile(path.join(qaDir, name));
    if (bytes.length < 100 || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw new Error(`Invalid PNG preview: ${name}`);
  }
  await fs.writeFile(path.join(qaDir, 'render_status.json'), JSON.stringify({
    previews_written_and_signature_verified: true, worker_exit_status: worker.status, worker_signal: worker.signal,
    note: worker.status === 0 ? 'Render worker completed normally.' : 'Native renderer exited during shutdown after valid PNGs were saved; XLSX authoring and content verification completed independently.',
  }, null, 2), 'utf8');
}
console.log(JSON.stringify({ xlsx: outputPath, records: rows.length, fields: fields.length, long_text_sidecars: externalized.length, previews: preview ? qaDir : null }));
// All required saves/checks are awaited above; finish this standalone CLI after
// success instead of running optional native-renderer shutdown callbacks.
process.exit(0);
