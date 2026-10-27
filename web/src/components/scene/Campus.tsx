import { Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";

import type { AlertTarget, Equipment, ScenarioResult } from "@/api/types";
import { number } from "@/lib/format";
import { useTwin } from "@/state/store";

import { campusLayout, densityColor, RACK, thermalColor, type CampusLayout } from "./layout";

export interface SceneProps {
  nHalls: number;
  rows: number;
  racksPerRow: number;
  kwPerRack: number;
  kwBounds: [number, number];
  thermalBounds: [number, number];
  batteryMwh: number;
  coolingType: string;
  result: ScenarioResult | null;
}

const COLORS = { ground: "#0e141b", slab: "#16202b", wall: "#2a3a4d", selected: "#5aa9e6", equipment: "#3a4a5c",
                 grid: "#7fb3e0", it: "#5aa9e6", cooling: "#9ed2c6", battery: "#f2b84b" };

export function CampusScene(props: SceneProps) {
  const layout = useMemo(() => campusLayout(props.nHalls, props.rows, props.racksPerRow),
                         [props.nHalls, props.rows, props.racksPerRow]);
  return (
    <Canvas shadows={false} dpr={[1, 2]} camera={{ fov: 40, near: 0.5, far: 5000, position: [0, 120, 160] }}
            gl={{ antialias: true, preserveDrawingBuffer: true }}
            onPointerMissed={() => useTwin.getState().select(null)}>
      <color attach="background" args={["#0b0f14"]} />
      <hemisphereLight args={["#cfe3ff", "#0b0f14", 0.9]} />
      <directionalLight position={[60, 120, 40]} intensity={1.1} />
      <Ground layout={layout} />
      <Halls layout={layout} {...props} />
      <Substation position={layout.substation} result={props.result} />
      <CoolingPlant position={layout.coolingPlant} result={props.result} width={layout.bounds.maxX - layout.bounds.minX - 40}
                    coolingType={props.coolingType} />
      <BatteryPark position={layout.battery} mwh={props.batteryMwh} />
      <Flows layout={layout} result={props.result} />
      <CameraRig layout={layout} />
    </Canvas>
  );
}

// ------------------------------------------------------------------------ équipements

function Selectable({ equipment, children, position }: { equipment: Equipment; children: ReactNode; position: [number, number, number] }) {
  const select = useTwin((s) => s.select);
  const onClick = (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); select(equipment); };
  return (
    <group position={position} onClick={onClick}
           onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = "pointer"; }}
           onPointerOut={() => { document.body.style.cursor = "auto"; }}>
      {children}
    </group>
  );
}

function useSelected(equipment: Equipment) {
  return useTwin((s) => s.selected === equipment);
}

function Label({ position, title, lines }: { position: [number, number, number]; title: string; lines: string[] }) {
  return (
    <Html position={position} center distanceFactor={undefined} zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
      <div className="num whitespace-nowrap rounded border border-border bg-panel/90 px-2 py-1 text-[11px] leading-tight text-text shadow">
        <div className="font-medium">{title}</div>
        {lines.map((l) => <div key={l} className="text-muted">{l}</div>)}
      </div>
    </Html>
  );
}

function Ground({ layout }: { layout: CampusLayout }) {
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[(minX + maxX) / 2, -0.05, (minZ + maxZ) / 2]}>
      <planeGeometry args={[maxX - minX + 60, maxZ - minZ + 60]} />
      <meshStandardMaterial color={COLORS.ground} />
    </mesh>
  );
}

function Halls({ layout, kwPerRack, kwBounds, thermalBounds, result }: { layout: CampusLayout } & SceneProps) {
  const selected = useSelected("hall");
  const heatmap = useTwin((s) => s.heatmap);
  const ref = useRef<THREE.InstancedMesh>(null);
  const thermal = result?.twin?.thermal;

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color();
    const inletMean = thermal ? (thermal.rack_inlet_c.edge + (thermal.rack_inlet_c.inner ?? thermal.rack_inlet_c.edge)) / 2 : 0;
    layout.racks.forEach((rack, i) => {
      matrix.setPosition(rack.x, RACK.height / 2, rack.z);
      mesh.setMatrixAt(i, matrix);
      if (heatmap && thermal) {
        const inlet = rack.edge ? thermal.rack_inlet_c.edge : (thermal.rack_inlet_c.inner ?? thermal.rack_inlet_c.edge);
        const outlet = inlet + (thermal.rack_outlet_mean_c - inletMean);
        color.set(thermalColor(outlet, thermalBounds[0], thermalBounds[1]));
      } else {
        color.set(densityColor(kwPerRack, kwBounds[0], kwBounds[1]));
      }
      mesh.setColorAt(i, color);
    });
    mesh.count = layout.racks.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [layout, kwPerRack, kwBounds, heatmap, thermal, thermalBounds]);

  const itMw = result?.twin?.flows_mw.mean.it;
  return (
    <Selectable equipment="hall" position={[0, 0, 0]}>
      {layout.halls.map((h) => (
        <group key={h.index} position={[h.x, 0, h.z]}>
          <mesh position={[0, 0.05, 0]}>
            <boxGeometry args={[h.width, 0.1, h.depth]} />
            <meshStandardMaterial color={selected ? "#1d2c3c" : COLORS.slab} />
          </mesh>
          <lineSegments position={[0, 2, 0]}>
            <edgesGeometry args={[new THREE.BoxGeometry(h.width, 4, h.depth)]} />
            <lineBasicMaterial color={selected ? COLORS.selected : COLORS.wall} />
          </lineSegments>
        </group>
      ))}
      {heatmap && thermal && layout.aisles.map((a, i) => {
        const inlet = thermal.rack_inlet_c.inner ?? thermal.rack_inlet_c.edge;
        const t = a.hot ? thermal.rack_outlet_mean_c : inlet;
        return (
          <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[a.x, 0.12, a.z]}>
            <planeGeometry args={[a.width, a.depth]} />
            <meshBasicMaterial color={thermalColor(t, thermalBounds[0], thermalBounds[1])} transparent opacity={0.85} />
          </mesh>
        );
      })}
      <instancedMesh ref={ref} args={[undefined, undefined, Math.max(1, layout.racks.length)]} key={layout.racks.length}>
        <boxGeometry args={[RACK.width * 0.92, RACK.height, RACK.depth]} />
        <meshStandardMaterial roughness={0.6} metalness={0.1} />
      </instancedMesh>
      <Label position={[0, 7, layout.halls[0] ? -layout.halls[0].depth / 2 - 2 : 0]} title="Halls informatiques"
             lines={[`${layout.halls.length} × ${layout.racks.length / Math.max(1, layout.halls.length)} racks`,
                     itMw !== undefined ? `${number(itMw, 1)} MW IT moyens` : ""].filter(Boolean)} />
    </Selectable>
  );
}

function Substation({ position, result }: { position: [number, number, number]; result: ScenarioResult | null }) {
  const selected = useSelected("substation");
  const twin = result?.twin;
  const over = twin ? twin.peak_grid_mw > twin.grid_capacity_mw : false;
  return (
    <Selectable equipment="substation" position={position}>
      {[-4, 0, 4].map((dz) => (
        <mesh key={dz} position={[0, 1.6, dz]}>
          <boxGeometry args={[4, 3.2, 3]} />
          <meshStandardMaterial color={selected ? COLORS.selected : over ? "#8a3a36" : COLORS.equipment} />
        </mesh>
      ))}
      <mesh position={[0, 0.05, 0]}>
        <boxGeometry args={[10, 0.1, 16]} />
        <meshStandardMaterial color={COLORS.slab} />
      </mesh>
      <Label position={[0, 7, 0]} title="Poste électrique"
             lines={twin ? [`pointe ${number(twin.peak_grid_mw, 1)} / ${number(twin.grid_capacity_mw, 1)} MW`] : []} />
    </Selectable>
  );
}

function CoolingPlant({ position, result, width, coolingType }: { position: [number, number, number]; result: ScenarioResult | null; width: number; coolingType: string }) {
  const selected = useSelected("cooling_plant");
  const thermal = result?.twin?.thermal;
  const rated = thermal?.chiller_rated_cooling_mw ?? 0;
  const load = thermal?.chiller_load_factor_mean ?? 0;
  const chillers = Math.max(1, Math.min(24, Math.ceil(rated / 2)));
  const towers = Math.max(1, Math.ceil(chillers / 2));
  const span = Math.max(width, chillers * 5);
  const fans = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    // vitesse des ventilateurs proportionnelle au facteur de charge moyen du chiller
    fans.current?.children.forEach((fan) => { fan.rotation.y += dt * (0.5 + 8 * load); });
  });
  return (
    <Selectable equipment="cooling_plant" position={position}>
      <mesh position={[0, 0.05, 0]}>
        <boxGeometry args={[span, 0.1, 12]} />
        <meshStandardMaterial color={COLORS.slab} />
      </mesh>
      <group ref={fans}>
        {Array.from({ length: chillers }, (_, i) => {
          const x = -span / 2 + (i + 0.5) * (span / (chillers + towers));
          return (
            <group key={`c${i}`} position={[x, 0, -2]}>
              <mesh position={[0, 1.2, 0]}>
                <boxGeometry args={[3.2, 2.4, 2.2]} />
                <meshStandardMaterial color={selected ? COLORS.selected : COLORS.equipment} />
              </mesh>
              <mesh position={[0, 2.5, 0]}>
                <cylinderGeometry args={[0.8, 0.8, 0.1, 6]} />
                <meshStandardMaterial color={COLORS.cooling} />
              </mesh>
            </group>
          );
        })}
      </group>
      {Array.from({ length: towers }, (_, i) => {
        const x = -span / 2 + (chillers + i + 0.5) * (span / (chillers + towers));
        return (
          <mesh key={`t${i}`} position={[x, 2.5, 2.5]}>
            <cylinderGeometry args={[1.4, 1.9, 5, 16]} />
            <meshStandardMaterial color={selected ? COLORS.selected : "#4a5b6e"} />
          </mesh>
        );
      })}
      <Label position={[0, 8, 0]} title="Centrale de refroidissement"
             lines={thermal ? [`${coolingType === "liquid" ? "liquide + air" : coolingType === "air_free_cooling" ? "air + free cooling" : "air + chiller"}`,
                               `charge chiller ${number(load * 100, 0)} %`] : []} />
    </Selectable>
  );
}

function BatteryPark({ position, mwh }: { position: [number, number, number]; mwh: number }) {
  const selected = useSelected("battery");
  const containers = Math.min(40, Math.ceil(mwh / 4));
  const perRow = 4;
  return (
    <Selectable equipment="battery" position={position}>
      <mesh position={[0, 0.05, 0]}>
        <boxGeometry args={[12, 0.1, Math.max(6, Math.ceil(containers / perRow) * 3 + 2)]} />
        <meshStandardMaterial color={selected ? "#1d2c3c" : COLORS.slab} />
      </mesh>
      {Array.from({ length: containers }, (_, i) => (
        <mesh key={i} position={[-4.5 + (i % perRow) * 3, 1.3, -1.5 + Math.floor(i / perRow) * 3]}>
          <boxGeometry args={[2.4, 2.6, 2.2]} />
          <meshStandardMaterial color={selected ? COLORS.selected : "#6b5a2e"} />
        </mesh>
      ))}
      <Label position={[0, 6, 0]} title="Parc batterie" lines={[mwh > 0 ? `${number(mwh, 0)} MWh` : "aucune — cliquer pour en ajouter"]} />
    </Selectable>
  );
}

// ------------------------------------------------------------------------ flux d'énergie

function Flows({ layout, result }: { layout: CampusLayout; result: ScenarioResult | null }) {
  const flows = result?.twin?.flows_mw.mean;
  if (!flows) return null;
  const max = Math.max(1e-6, flows.grid, flows.it, flows.cooling);
  const s = layout.substation;
  const c = layout.coolingPlant;
  const b = layout.battery;
  const perHall = flows.it / Math.max(1, layout.halls.length);
  const items: { from: [number, number, number]; to: [number, number, number]; mw: number; color: string; key: string }[] = [
    { key: "grid", from: [s[0] - 30, 1, s[2]], to: [s[0] - 4, 1, s[2]], mw: flows.grid, color: COLORS.grid },
    ...layout.halls.map((h) => ({ key: `it${h.index}`, from: [s[0] + 5, 1, s[2]] as [number, number, number],
                                  to: [h.x, 1, -h.depth / 4] as [number, number, number], mw: perHall, color: COLORS.it })),
    { key: "cooling", from: [s[0] + 5, 1, s[2] + 4], to: [c[0], 1, c[2] - 6], mw: flows.cooling, color: COLORS.cooling },
  ];
  if (flows.battery_charge > 1e-6) items.push({ key: "bc", from: [s[0], 1, s[2] + 8], to: [b[0], 1, b[2] - 3], mw: flows.battery_charge, color: COLORS.battery });
  if (flows.battery_discharge > 1e-6) items.push({ key: "bd", from: [b[0] + 2, 1, b[2] - 3], to: [s[0] + 2, 1, s[2] + 8], mw: flows.battery_discharge, color: COLORS.battery });
  return <>{items.map(({ key, ...f }) => <FlowLine key={key} {...f} width={1 + 9 * (f.mw / max)} />)}</>;
}

function FlowLine({ from, to, width, color }: { from: [number, number, number]; to: [number, number, number]; width: number; color: string }) {
  // tracé en L au sol ; épaisseur proportionnelle aux MW, tirets animés dans le sens du flux
  const points = useMemo(() => [new THREE.Vector3(...from), new THREE.Vector3(from[0], from[1], to[2]), new THREE.Vector3(...to)], [from, to]);
  const ref = useRef<{ material: { dashOffset: number } } | null>(null);
  useFrame((_, dt) => { if (ref.current) ref.current.material.dashOffset -= dt * 6; });
  return <Line ref={ref as never} points={points} color={color} lineWidth={width} dashed dashSize={2} gapSize={1.2} transparent opacity={0.9} />;
}

// ------------------------------------------------------------------------ caméra

function CameraRig({ layout }: { layout: CampusLayout }) {
  const focus = useTwin((s) => s.focus);
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera } = useThree();
  const animation = useRef<{ position: THREE.Vector3; target: THREE.Vector3; t: number } | null>(null);
  const extent = Math.max(layout.bounds.maxX - layout.bounds.minX, layout.bounds.maxZ - layout.bounds.minZ);

  const targets = useMemo<Record<AlertTarget, [number, number, number]>>(() => ({
    campus: [(layout.bounds.minX + layout.bounds.maxX) / 2, 0, (layout.bounds.minZ + layout.bounds.maxZ) / 2],
    substation: layout.substation, battery: layout.battery, cooling_plant: layout.coolingPlant,
    hall: layout.hallCenter, site: [(layout.bounds.minX + layout.bounds.maxX) / 2, 0, 0],
  }), [layout]);

  const goTo = (target: AlertTarget) => {
    const t = new THREE.Vector3(...targets[target]);
    const wide = target === "campus" || target === "site";
    const distance = wide ? extent * 1.3 : target === "hall" ? extent * 0.8 : Math.max(35, extent * 0.3);
    // vue plongeante : la centrale (au premier plan) reste au-dessus des légendes
    if (wide) t.z += extent * 0.08;
    animation.current = { target: t, position: t.clone().add(new THREE.Vector3(0, distance * 0.92, distance * 0.42)), t: 0 };
  };

  useEffect(() => { goTo("campus"); }, [extent]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (focus) goTo(focus.target); }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame((_, dt) => {
    const a = animation.current;
    if (!a || !controls.current) return;
    a.t = Math.min(1, a.t + dt * 1.6);
    const k = 1 - Math.pow(1 - a.t, 3);
    camera.position.lerp(a.position, k);
    controls.current.target.lerp(a.target, k);
    controls.current.update();
    if (a.t >= 1) animation.current = null;
  });
  return <OrbitControls ref={controls} makeDefault maxPolarAngle={Math.PI / 2.1} enableDamping />;
}
