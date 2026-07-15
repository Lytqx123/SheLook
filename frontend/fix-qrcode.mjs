// Fix @rc-component/qrcode@2.0.0 ESM publishing defect
// The es/hooks/useQRCode.js file is missing, causing React error #130.
// This script inlines the useQRCode hook into QRCodeCanvas.js and QRCodeSVG.js,
// removing the dependency on the missing ./hooks/useQRCode module.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const esDir = path.join(__dirname, 'node_modules', '@rc-component', 'qrcode', 'es');

const useQRCodeInline = `import { QrCode, QrSegment } from "./libs/qrcodegen";
import { ERROR_LEVEL_MAP, getMarginSize, getImageSettings } from "./utils";
const useQRCode = opt => {
  const { value, level, minVersion, includeMargin, marginSize, imageSettings, size, boostLevel } = opt;
  const memoizedQrcode = React.useMemo(() => {
    const values = Array.isArray(value) ? value : [value];
    const segments = values.reduce((acc, val) => { acc.push(...QrSegment.makeSegments(val)); return acc; }, []);
    return QrCode.encodeSegments(segments, ERROR_LEVEL_MAP[level], minVersion, undefined, undefined, boostLevel);
  }, [value, level, minVersion, boostLevel]);
  return React.useMemo(() => {
    const cs = memoizedQrcode.getModules();
    const mg = getMarginSize(includeMargin, marginSize);
    const ncs = cs.length + mg * 2;
    const cis = getImageSettings(cs, size, mg, imageSettings);
    return { cells: cs, margin: mg, numCells: ncs, calculatedImageSettings: cis, qrcode: memoizedQrcode };
  }, [memoizedQrcode, size, imageSettings, includeMargin, marginSize]);
};`;

function patchFile(filename, originalUtilsImport, newUtilsImport) {
  const filePath = path.join(esDir, filename);
  if (!fs.existsSync(filePath)) {
    console.log(`Skip: ${filename} not found`);
    return;
  }
  let content = fs.readFileSync(filePath, 'utf8');
  // Skip if already patched
  if (!content.includes('from "./hooks/useQRCode"')) {
    console.log(`Skip: ${filename} already patched or no hook import`);
    return;
  }
  // Remove the broken import line
  content = content.replace(/import \{ useQRCode \} from "\.\/hooks\/useQRCode";\n/, '');
  // Replace the utils import to include the extra exports
  content = content.replace(originalUtilsImport, newUtilsImport);
  // Add the inline useQRCode implementation after the imports
  content = content.replace(
    newUtilsImport + ';\n',
    newUtilsImport + ';\n' + useQRCodeInline.replace(/^import [^\n]+\n/gm, '') + '\n'
  );
  fs.writeFileSync(filePath, content, 'utf8');
  console.log(`Fixed: ${filename}`);
}

// Patch QRCodeCanvas.js
patchFile(
  'QRCodeCanvas.js',
  'import { DEFAULT_BACKGROUND_COLOR, DEFAULT_FRONT_COLOR, DEFAULT_NEED_MARGIN, DEFAULT_LEVEL, DEFAULT_MINVERSION, DEFAULT_SIZE, isSupportPath2d, excavateModules, generatePath } from "./utils"',
  'import { QrCode, QrSegment } from "./libs/qrcodegen";\nimport { DEFAULT_BACKGROUND_COLOR, DEFAULT_FRONT_COLOR, DEFAULT_NEED_MARGIN, DEFAULT_LEVEL, DEFAULT_MINVERSION, DEFAULT_SIZE, ERROR_LEVEL_MAP, getMarginSize, getImageSettings, isSupportPath2d, excavateModules, generatePath } from "./utils"'
);

// Patch QRCodeSVG.js
patchFile(
  'QRCodeSVG.js',
  'import { DEFAULT_BACKGROUND_COLOR, DEFAULT_FRONT_COLOR, DEFAULT_NEED_MARGIN, DEFAULT_LEVEL, DEFAULT_MINVERSION, DEFAULT_SIZE, excavateModules, generatePath } from "./utils"',
  'import { QrCode, QrSegment } from "./libs/qrcodegen";\nimport { DEFAULT_BACKGROUND_COLOR, DEFAULT_FRONT_COLOR, DEFAULT_NEED_MARGIN, DEFAULT_LEVEL, DEFAULT_MINVERSION, DEFAULT_SIZE, ERROR_LEVEL_MAP, getMarginSize, getImageSettings, excavateModules, generatePath } from "./utils"'
);

console.log('Done: @rc-component/qrcode ESM patch applied');
