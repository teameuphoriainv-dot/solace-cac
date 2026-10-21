/**
 * Emergency room numbers for hospitals inside and next to Illinois's 16th District.
 *
 * Source: CMS Provider Data Catalog, "Timely and Effective Care - Hospital"
 * (dataset yv7e-xc69) and "Timely and Effective Care - State" (dataset apyc-v239).
 * Both files were last updated by CMS on 2026-07-22 and downloaded on 2026-10-18.
 *
 *   OP_18b  median minutes from arriving at the ER to leaving, for patients who
 *           were sent home (10/01/2024 to 09/30/2025)
 *   OP_22   percent of ER patients who left before being seen (01/01/2024 to 12/31/2024)
 *
 * Which district a hospital is in: its CMS street address run through the U.S.
 * Census Bureau geocoder (119th Congress districts) on 2026-10-18. Five addresses
 * did not match, so their map location (OpenStreetMap) went through the Census
 * coordinate lookup instead: Pontiac and Galena are in the 16th, Mendota and DeKalb
 * are in the 14th, Crystal Lake is in the 9th. The page names towns, not hospitals;
 * cmsId is the CMS facility id, so anyone can look a row up on Medicare Care Compare.
 *
 * Left out on purpose: the Galena hospital (inside the district, but CMS has no ER
 * numbers for it) and every hospital outside the district except the city ERs below.
 */

export type ErSite = {
  cmsId: string;
  town: string;
  /** OP_18b, minutes. */
  minutes: number;
  /** OP_22, percent. Null when CMS reports "Not Available". */
  leftPct: number | null;
};

export const IL16_SOURCE = {
  datasetUrl: "https://data.cms.gov/provider-data/dataset/yv7e-xc69",
  stateDatasetUrl: "https://data.cms.gov/provider-data/dataset/apyc-v239",
  updated: "July 22, 2026",
  downloaded: "October 18, 2026",
  timeMeasure: "OP_18b",
  timePeriod: "October 1, 2024 to September 30, 2025",
  leftMeasure: "OP_22",
  leftPeriod: "January 1 to December 31, 2024",
  districtCheck: "U.S. Census Bureau geocoder, 119th Congress districts",
};

/** CMS state file, Illinois rows. */
export const ILLINOIS = { minutes: 162, leftPct: 3 };

/** Hospital ERs whose address is inside the 16th District. */
export const INSIDE_DISTRICT: ErSite[] = [
  { cmsId: "140012", town: "Dixon", minutes: 180, leftPct: 2 },
  { cmsId: "140101", town: "Morris", minutes: 170, leftPct: 1 },
  { cmsId: "141330", town: "Hopedale", minutes: 130, leftPct: null },
  { cmsId: "140161", town: "Pontiac", minutes: 126, leftPct: 1 },
  { cmsId: "141335", town: "Harvard", minutes: 118, leftPct: 1 },
  { cmsId: "140120", town: "Pekin", minutes: 115, leftPct: 1 },
  { cmsId: "141337", town: "Princeton", minutes: 112, leftPct: 0 },
  { cmsId: "141319", town: "Geneseo", minutes: 108, leftPct: null },
  { cmsId: "141312", town: "Rochelle", minutes: 96, leftPct: 2 },
  { cmsId: "141309", town: "Eureka", minutes: 90, leftPct: 1 },
];

/**
 * The big city ERs in Rockford and Peoria. Parts of both cities are in the 16th
 * District, but every one of these hospital addresses sits in the 17th.
 */
export const NEARBY_CITY_ERS: ErSite[] = [
  { cmsId: "140239", town: "Rockford", minutes: 258, leftPct: 6 },
  { cmsId: "140233", town: "Rockford", minutes: 223, leftPct: 2 },
  { cmsId: "140228", town: "Rockford", minutes: 217, leftPct: 2 },
  { cmsId: "140067", town: "Peoria", minutes: 286, leftPct: 4 },
  { cmsId: "140209", town: "Peoria", minutes: 213, leftPct: 6 },
  { cmsId: "140013", town: "Peoria", minutes: 150, leftPct: 1 },
];

export function formatMinutes(m: number): string {
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h === 0) return `${m} min`;
  return rest === 0 ? `${h} hr` : `${h} hr ${rest} min`;
}
