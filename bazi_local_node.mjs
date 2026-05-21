import { readFileSync } from 'node:fs';
import { getBaziDetail } from 'bazi-mcp';
import { LunarHour } from 'tyme4ts';
import { buildBazi } from './node_modules/bazi-mcp/dist/lib/bazi.js';

function cleanArgs(input) {
  const args = {};
  if (input.lunarDatetime) {
    args.lunarDatetime = String(input.lunarDatetime);
    args.lunarIsLeapMonth = Boolean(input.lunarIsLeapMonth);
  } else if (input.solarDatetime) {
    args.solarDatetime = String(input.solarDatetime);
  }

  if (!args.lunarDatetime && !args.solarDatetime) {
    throw new Error('solarDatetime or lunarDatetime is required');
  }

  const gender = Number(input.gender ?? 1);
  args.gender = Number.isFinite(gender) && (gender === 0 || gender === 1) ? gender : 1;

  const sect = Number(input.eightCharProviderSect ?? 2);
  args.eightCharProviderSect = sect === 1 || sect === 2 ? sect : 2;

  return args;
}

function parseLunarDatetime(value) {
  const match = String(value || '').trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/);
  if (!match) {
    throw new Error(`invalid lunarDatetime: ${value}`);
  }
  const [, year, month, day, hour, minute, second = '0'] = match;
  return [year, month, day, hour, minute, second].map((part) => Number(part));
}

function getLocalLunarBazi(args) {
  const [year, monthValue, day, hour, minute, second] = parseLunarDatetime(args.lunarDatetime);
  const month = args.lunarIsLeapMonth ? -Math.abs(monthValue) : monthValue;
  const lunarHour = LunarHour.fromYmdHms(year, month, day, hour, minute, second);
  return buildBazi({
    lunarHour,
    gender: args.gender,
    eightCharProviderSect: args.eightCharProviderSect,
  });
}

try {
  const raw = readFileSync(0, 'utf8').trim();
  const input = raw ? JSON.parse(raw) : {};
  const args = cleanArgs(input);
  const data = args.lunarDatetime ? getLocalLunarBazi(args) : await getBaziDetail(args);
  process.stdout.write(JSON.stringify({ success: true, data }));
} catch (error) {
  process.stderr.write(JSON.stringify({
    success: false,
    error_type: error?.name || 'Error',
    error: error?.message || String(error),
  }));
  process.exit(1);
}
