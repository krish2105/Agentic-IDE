"use client";

import { Billboard, Text } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import type { MissionControlRow } from "@sani/client";
import { Suspense, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { readToken } from "@/lib/tokens";

/**
 * Mission Control as navigable space.
 *
 * The encoding, which is the whole point -- every visual property carries a
 * fact rather than decorating one:
 *
 *   z position        recency        (newer sessions come toward you)
 *   emissive          activity       (a working agent glows)
 *   halo + pulse      needs approval (the only thing that pulses, per the rule)
 *   scale             context used   (a session eating its window looks heavy)
 *   colour            status
 *
 * A 2D grid fallback lives in MissionControlGrid; this component is only ever
 * mounted at quality tiers that allow 3D.
 */

interface Props {
  sessions: MissionControlRow[];
  onOpen: (sessionId: string) => void;
}

interface Placed {
  row: MissionControlRow;
  position: [number, number, number];
}

/** A stable pseudo-random in [0,1) from a session id, so a session keeps its
 *  place in space between renders instead of jittering on every poll. */
function seeded(id: string, salt: number): number {
  let hash = salt;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return (hash % 10000) / 10000;
}

function layout(sessions: MissionControlRow[]): Placed[] {
  // Sorted by elapsed so "recency" maps to depth predictably; the golden-angle
  // spiral keeps the cloud even rather than clumping at the centre.
  const ordered = [...sessions].sort((a, b) => a.elapsed_s - b.elapsed_s);
  const golden = Math.PI * (3 - Math.sqrt(5));

  return ordered.map((row, index) => {
    const radius = 1.5 + Math.sqrt(index) * 1.15;
    const angle = index * golden;
    const drift = (seeded(row.session_id, 7) - 0.5) * 1.6;
    return {
      row,
      position: [
        Math.cos(angle) * radius,
        drift + (seeded(row.session_id, 13) - 0.5) * 1.2,
        Math.sin(angle) * radius - index * 0.28,
      ],
    };
  });
}

function statusColor(row: MissionControlRow): string {
  if (row.approval_needed) return readToken("--color-attention", "#f5a524");
  switch (row.status) {
    case "executing":
    case "planning":
      return readToken("--color-agent", "#a78bfa");
    case "failed":
      return readToken("--color-danger", "#f87171");
    case "complete":
      return readToken("--color-ok", "#4ade80");
    default:
      return readToken("--color-ink-faint", "#5e6779");
  }
}

function SessionNode({ placed, onOpen }: { placed: Placed; onOpen: (id: string) => void }) {
  const group = useRef<THREE.Group>(null);
  const halo = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);

  const { row, position } = placed;
  const color = useMemo(() => statusColor(row), [row]);
  const active = row.status === "executing" || row.status === "planning";

  // Scale encodes how much of the context window this session has consumed.
  const scale = 0.34 + Math.min(row.total_steps, 12) * 0.012;

  useFrame((state, delta) => {
    if (!group.current) return;

    const t = state.clock.elapsedTime;
    // A working session breathes; an idle one is still. Peripheral vision
    // registers the difference without you reading anything.
    const breathe = active ? 1 + Math.sin(t * 2.2 + position[0]) * 0.035 : 1;
    const target = (hovered ? 1.22 : 1) * breathe;
    group.current.scale.lerp(new THREE.Vector3(target, target, target), delta * 8);
    group.current.rotation.y += delta * (active ? 0.35 : 0.08);

    if (halo.current) {
      // Faint and additive: a halo should read as light spilling off the node,
      // never as a disc painted behind it. Anything above ~0.05 stops looking
      // like glow and starts looking like a solid shell.
      const pulse = 0.5 + Math.sin(t * 2.6) * 0.5;
      (halo.current.material as THREE.MeshBasicMaterial).opacity = row.approval_needed
        ? 0.012 + pulse * 0.03
        : 0;
      const breath = 1 + pulse * 0.16;
      halo.current.scale.setScalar(scale * 2.6 * breath);
    }
  });

  return (
    <group
      ref={group}
      position={position}
      onClick={(event) => {
        event.stopPropagation();
        onOpen(row.session_id);
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "";
      }}
    >
      <mesh scale={scale}>
        <icosahedronGeometry args={[1, 1]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={active ? 1.5 : 0.35}
          roughness={0.35}
          metalness={0.1}
          flatShading
        />
      </mesh>

      {/* Wireframe shell: reads as "instrument", not "toy". */}
      <mesh scale={scale * 1.35}>
        <icosahedronGeometry args={[1, 0]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={hovered ? 0.5 : 0.18} />
      </mesh>

      {/* Attention halo. Only ever visible when a human decision is pending --
          the 3D equivalent of the amber pulse, and the only looping animation
          in the scene. */}
      <mesh ref={halo} scale={scale * 2.1}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.BackSide}
        />
      </mesh>

      {hovered && (
        <Billboard position={[0, scale * 2.1, 0]}>
          <Text
            fontSize={0.19}
            maxWidth={4}
            textAlign="center"
            anchorY="bottom"
            color={readToken("--color-ink", "#e9ecf3")}
            outlineWidth={0.012}
            outlineColor={readToken("--color-base", "#08090d")}
          >
            {row.task.length > 52 ? `${row.task.slice(0, 52)}…` : row.task}
          </Text>
        </Billboard>
      )}
    </group>
  );
}

/**
 * Slow orbital drift plus pointer parallax.
 *
 * The orbit radius is derived from where the nodes actually are rather than
 * from a guessed constant: a fixed radius frames three sessions beautifully and
 * strands thirty as specks in the middle distance.
 */
function Rig({ placed }: { placed: Placed[] }) {
  const radius = useMemo(() => {
    if (placed.length === 0) return 9;
    const extent = Math.max(
      ...placed.map(({ position }) =>
        Math.hypot(position[0], position[1], position[2]),
      ),
    );
    // Fit the furthest node into roughly two thirds of the frame.
    return THREE.MathUtils.clamp(extent * 1.9 + 2.6, 6, 22);
  }, [placed]);

  useFrame((state, delta) => {
    const { camera, pointer } = state;
    const t = state.clock.elapsedTime * 0.045;

    const target = new THREE.Vector3(
      Math.sin(t) * radius + pointer.x * 1.4,
      radius * 0.22 + pointer.y * 0.9,
      Math.cos(t) * radius,
    );
    camera.position.lerp(target, delta * 1.2);
    camera.lookAt(0, 0, 0);
  });
  return null;
}

/**
 * A faint reference grid on the floor of the scene.
 *
 * Without a ground plane the nodes read as blobs floating in a void: there is
 * nothing for the eye to measure depth against, so the z-axis encoding is
 * wasted. The grid is deliberately near-invisible -- it only has to give
 * parallax something to work with.
 */
function ReferenceGrid() {
  const color = useMemo(() => readToken("--color-edge-strong", "#333a4d"), []);
  return (
    <gridHelper
      args={[42, 42, color, color]}
      position={[0, -3.4, 0]}
      material-transparent
      material-opacity={0.12}
      material-depthWrite={false}
    />
  );
}

/** Static motes. Cheap parallax reference -- they are not data and never
 *  respond to input. */
function Dust({ count = 90 }: { count?: number }) {
  const geometry = useMemo(() => {
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i += 1) {
      positions[i * 3] = (Math.random() - 0.5) * 34;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 16;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 34;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return geo;
  }, [count]);

  const color = useMemo(() => readToken("--color-ink-faint", "#5e6779"), []);

  return (
    <points geometry={geometry}>
      <pointsMaterial
        size={0.045}
        color={color}
        transparent
        opacity={0.55}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

export default function MissionControl3D({ sessions, onOpen }: Props) {
  const placed = useMemo(() => layout(sessions), [sessions]);

  return (
    <Canvas
      dpr={[1, 1.75]}
      gl={{ antialias: true, alpha: true }}
      camera={{ position: [0, 2.5, 9], fov: 46 }}
    >
      <ambientLight intensity={0.7} />
      <pointLight position={[6, 8, 6]} intensity={70} distance={45} decay={2} />
      <pointLight position={[-8, -4, -6]} intensity={30} distance={45} decay={2} />

      <ReferenceGrid />
      <Dust />

      <Suspense fallback={null}>
        {placed.map((item) => (
          <SessionNode key={item.row.session_id} placed={item} onOpen={onOpen} />
        ))}
      </Suspense>

      <Rig placed={placed} />
    </Canvas>
  );
}
