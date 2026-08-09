"use client";

import { Billboard, Line, Text } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import type { PlanStep, StepStatus } from "@sani/client";
import { Suspense, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { readToken } from "@/lib/tokens";

/**
 * The agent's plan, executing, in three dimensions.
 *
 * This is the surface that finally renders `rag.retrieved`. Retrieval already
 * fires before every plan and steers it, and until now nothing showed it --
 * which is precisely the opacity the approval gate exists to prevent, just one
 * layer earlier. Here the retrieved chunks are visible objects with beams into
 * the step that consumed them: you can see what the agent read before it
 * decided.
 *
 * Legibility beats spectacle. A pretty graph nobody can read is worse than the
 * ordered list it replaced, so: steps stay on a clear left-to-right spine,
 * status is carried by colour *and* by a written label, and the camera does not
 * wander far enough to lose the reading order.
 */

interface Props {
  steps: PlanStep[];
  currentStep: number | null;
  retrieved: string[];
  /** Paused when the tab is not visible: an off-screen render loop is pure
   *  waste, and the work surface wins every performance tradeoff. */
  active: boolean;
}

const STATUS_COLOR: Record<StepStatus, string> = {
  pending: "--color-ink-faint",
  running: "--color-agent",
  complete: "--color-ok",
  rejected: "--color-attention",
  failed: "--color-danger",
  skipped: "--color-ink-faint",
};

const STATUS_LABEL: Record<StepStatus, string> = {
  pending: "pending",
  running: "running",
  complete: "done",
  rejected: "rejected",
  failed: "failed",
  skipped: "skipped",
};

const SPINE_SPACING = 2.2;

function StepNode({
  step,
  position,
  isCurrent,
}: {
  step: PlanStep;
  position: [number, number, number];
  isCurrent: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);

  const color = useMemo(
    () => readToken(STATUS_COLOR[step.status], "#5e6779"),
    [step.status],
  );
  const running = step.status === "running";

  useFrame((state, delta) => {
    if (!group.current) return;
    const t = state.clock.elapsedTime;
    // Only the running step moves. Stillness elsewhere is what makes the
    // moving one findable without reading.
    const pulse = running ? 1 + Math.sin(t * 3.2) * 0.08 : 1;
    const target = (hovered ? 1.15 : 1) * pulse;
    group.current.scale.lerp(new THREE.Vector3(target, target, target), delta * 9);
    if (running) group.current.rotation.y += delta * 0.9;
  });

  return (
    <group
      ref={group}
      position={position}
      onPointerOver={(event) => {
        event.stopPropagation();
        setHovered(true);
      }}
      onPointerOut={() => setHovered(false)}
    >
      <mesh scale={0.42}>
        <icosahedronGeometry args={[1, 1]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={running ? 1.6 : isCurrent ? 0.8 : 0.3}
          roughness={0.4}
          flatShading
        />
      </mesh>

      <mesh scale={0.58}>
        <icosahedronGeometry args={[1, 0]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.25} />
      </mesh>

      <Billboard position={[0, 0.8, 0]}>
        <Text
          fontSize={0.155}
          maxWidth={2.0}
          textAlign="center"
          anchorY="bottom"
          color={readToken("--color-ink", "#e9ecf3")}
          outlineWidth={0.012}
          outlineColor={readToken("--color-base", "#08090d")}
        >
          {step.description.length > 34
            ? `${step.description.slice(0, 34)}…`
            : step.description}
        </Text>
        <Text
          position={[0, -0.28, 0]}
          fontSize={0.115}
          anchorY="bottom"
          color={color}
          outlineWidth={0.01}
          outlineColor={readToken("--color-base", "#08090d")}
        >
          {`${step.tool} · ${STATUS_LABEL[step.status]}`}
        </Text>
      </Billboard>
    </group>
  );
}

/** A retrieved chunk, and the beam showing it fed the plan. */
function RetrievalNode({
  label,
  position,
  target,
}: {
  label: string;
  position: [number, number, number];
  target: [number, number, number];
}) {
  const color = readToken("--color-agent", "#a78bfa");
  const points = useMemo<[number, number, number][]>(
    () => [position, target],
    [position, target],
  );

  return (
    <group>
      <Line points={points} color={color} lineWidth={1} transparent opacity={0.22} />
      <mesh position={position} scale={0.14}>
        <octahedronGeometry args={[1, 0]} />
        <meshBasicMaterial color={color} transparent opacity={0.75} />
      </mesh>
      <Billboard position={[position[0], position[1] - 0.34, position[2]]}>
        <Text
          fontSize={0.12}
          maxWidth={3}
          textAlign="center"
          color={readToken("--color-ink-faint", "#5e6779")}
        >
          {label.length > 34 ? `…${label.slice(-33)}` : label}
        </Text>
      </Billboard>
    </group>
  );
}

/** Keeps the whole spine in frame and follows the running step. */
function Rig({
  count,
  focus,
  hasRetrieval,
}: {
  count: number;
  focus: number | null;
  hasRetrieval: boolean;
}) {
  useFrame((state, delta) => {
    const { camera, pointer, viewport } = state;
    const span = Math.max(1, count - 1) * SPINE_SPACING;

    // The retrieval cluster sits ~3.1 to the left of the first node, so the
    // framing has to account for it or the thing this panel exists to show is
    // the first thing off-screen.
    const leftExtent = -span / 2 - (hasRetrieval ? 4.4 : 1.2);
    const rightExtent = span / 2 + 1.2;
    const contentCentre = (leftExtent + rightExtent) / 2;
    const contentWidth = rightExtent - leftExtent;

    // Narrow docks need the camera further back for the same content.
    const aspect = Math.max(0.6, viewport.width / Math.max(viewport.height, 0.001));
    const distance = THREE.MathUtils.clamp(contentWidth / (1.35 * aspect) + 2.4, 6, 20);

    // Bias gently toward the running step without losing the rest of the graph.
    const focusX = focus !== null ? focus * SPINE_SPACING - span / 2 : contentCentre;
    const lookX = contentCentre * 0.75 + focusX * 0.25;

    const target = new THREE.Vector3(
      lookX + pointer.x * 0.9,
      0.9 + pointer.y * 0.6,
      distance,
    );
    camera.position.lerp(target, delta * 1.6);
    camera.lookAt(lookX, -0.15, 0);
  });
  return null;
}

function Scene({ steps, currentStep, retrieved }: Omit<Props, "active">) {
  const span = Math.max(1, steps.length - 1) * SPINE_SPACING;

  // Zigzag rather than a straight line: in a ~390px dock a flat spine puts
  // every label on one baseline and they collide into unreadable mush. The
  // alternation buys each label its own band.
  const positions = useMemo<[number, number, number][]>(
    () =>
      steps.map((_, index) => [
        index * SPINE_SPACING - span / 2,
        index % 2 === 0 ? 0.34 : -0.62,
        0,
      ]),
    [steps, span],
  );

  // Retrieval fed the *plan*, not any one step, so beams converge on the first
  // step -- where planning became action.
  const anchor = positions[0] ?? ([0, 0, 0] as [number, number, number]);

  const chunkPositions = useMemo<[number, number, number][]>(
    () =>
      retrieved.map((_, index) => {
        const spread = (index - (retrieved.length - 1) / 2) * 1.15;
        return [anchor[0] - 3.1, 1.5 + spread * 0.32, spread * 0.55];
      }),
    [retrieved, anchor],
  );

  return (
    <>
      <ambientLight intensity={0.75} />
      <pointLight position={[4, 6, 6]} intensity={55} distance={40} decay={2} />

      {/* The spine. Edges are drawn under the nodes so status colour reads. */}
      {positions.length > 1 && (
        <Line
          points={positions}
          color={readToken("--color-edge-strong", "#333a4d")}
          lineWidth={1}
          transparent
          opacity={0.5}
        />
      )}

      {steps.map((step, index) => (
        <StepNode
          key={step.index}
          step={step}
          position={positions[index]}
          isCurrent={step.index === currentStep}
        />
      ))}

      {retrieved.map((label, index) => (
        <RetrievalNode
          key={label}
          label={label}
          position={chunkPositions[index]}
          target={anchor}
        />
      ))}

      <Rig count={steps.length} focus={currentStep} hasRetrieval={retrieved.length > 0} />
    </>
  );
}

export default function CognitionGraph({ steps, currentStep, retrieved, active }: Props) {
  if (steps.length === 0) {
    return (
      <p className="px-1 text-xs text-ink-faint">
        No plan yet — the graph appears once the agent has proposed one.
      </p>
    );
  }

  return (
    <div className="h-[300px] overflow-hidden rounded-xl border border-edge bg-base/40">
      <Canvas
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
        camera={{ position: [0, 1.6, 9], fov: 45 }}
        // Capped below 60 and stopped entirely when the tab is hidden: this
        // shares a machine with the editor, and the editor wins.
        frameloop={active ? "always" : "never"}
      >
        {/* drei's <Text> suspends while its font loads. Without a boundary
            the whole canvas stays blank until it resolves -- which reads as
            a broken feature rather than a loading one. */}
        <Suspense fallback={null}>
          <Scene steps={steps} currentStep={currentStep} retrieved={retrieved} />
        </Suspense>
      </Canvas>
    </div>
  );
}
