// Disposition géométrique du campus (mètres). Conventions visuelles uniquement : les
// quantités métier (rangées, racks, MW, MWh…) viennent du scénario et des résultats.

export const RACK = { width: 0.6, depth: 1.2, height: 2.2 };
export const AISLE = 1.2;
const ROW_PITCH = RACK.depth + AISLE;
const HALL_MARGIN = 3;
const HALL_GAP = 8;

export interface HallLayout { index: number; x: number; z: number; width: number; depth: number }
export interface CampusLayout {
  halls: HallLayout[];
  racks: { x: number; z: number; hall: number; row: number; edge: boolean }[];
  aisles: { x: number; z: number; width: number; depth: number; hot: boolean }[];
  bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
  substation: [number, number, number];
  coolingPlant: [number, number, number];
  battery: [number, number, number];
  hallCenter: [number, number, number];
}

export function campusLayout(nHalls: number, rows: number, racksPerRow: number): CampusLayout {
  const hallWidth = racksPerRow * RACK.width + 2 * HALL_MARGIN;
  const hallDepth = rows * ROW_PITCH + 2 * HALL_MARGIN - AISLE;
  const totalWidth = nHalls * hallWidth + (nHalls - 1) * HALL_GAP;
  const halls: HallLayout[] = [];
  const racks: CampusLayout["racks"] = [];
  const aisles: CampusLayout["aisles"] = [];
  for (let h = 0; h < nHalls; h++) {
    const x0 = -totalWidth / 2 + h * (hallWidth + HALL_GAP);
    halls.push({ index: h, x: x0 + hallWidth / 2, z: 0, width: hallWidth, depth: hallDepth });
    for (let r = 0; r < rows; r++) {
      const z = -hallDepth / 2 + HALL_MARGIN + RACK.depth / 2 + r * ROW_PITCH;
      for (let k = 0; k < racksPerRow; k++) {
        racks.push({ x: x0 + HALL_MARGIN + RACK.width / 2 + k * RACK.width, z, hall: h, row: r,
                     edge: r === 0 || r === rows - 1 });
      }
      if (r < rows - 1) {
        // allées alternées froides / chaudes entre rangées
        aisles.push({ x: x0 + hallWidth / 2, z: z + ROW_PITCH / 2, width: racksPerRow * RACK.width,
                      depth: AISLE, hot: r % 2 === 0 });
      }
    }
  }
  const maxZ = hallDepth / 2;
  const minX = -totalWidth / 2;
  const plantDepth = 14;
  return {
    halls, racks, aisles,
    bounds: { minX: minX - 34, maxX: totalWidth / 2, minZ: -maxZ - 22, maxZ: maxZ + plantDepth + 6 },
    substation: [minX - 20, 0, -maxZ / 2],
    battery: [minX - 20, 0, maxZ / 2 + 6],
    coolingPlant: [0, 0, maxZ + plantDepth / 2 + 4],
    hallCenter: [0, 0, 0],
  };
}

// --------------------------------------------------------------------- échelles de couleur

const DENSITY_STOPS = ["#2c7bb6", "#00a6ca", "#00ccbc", "#90eb9d", "#f9d057", "#f29e2e", "#d7191c"];
const THERMAL_STOPS = ["#3b6ea8", "#5aa9e6", "#9ed2c6", "#f2d16b", "#f29e2e", "#e5533d", "#a3181f"];

function interpolate(stops: string[], t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = parseInt(stops[i].slice(1), 16);
  const b = parseInt(stops[i + 1].slice(1), 16);
  const mix = (shift: number) => Math.round(((a >> shift) & 255) * (1 - f) + ((b >> shift) & 255) * f);
  return `#${((mix(16) << 16) | (mix(8) << 8) | mix(0)).toString(16).padStart(6, "0")}`;
}

export const densityColor = (kw: number, min: number, max: number) => interpolate(DENSITY_STOPS, (kw - min) / (max - min));
export const thermalColor = (t: number, min: number, max: number) => interpolate(THERMAL_STOPS, (t - min) / (max - min));
export const gradient = (kind: "density" | "thermal") =>
  `linear-gradient(90deg, ${(kind === "density" ? DENSITY_STOPS : THERMAL_STOPS).join(", ")})`;
