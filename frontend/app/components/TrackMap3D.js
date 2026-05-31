"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import * as THREE from "three";

const DRIVER1_COLOR = 0x16a34a;
const DRIVER2_COLOR = 0xdc2626;
const TRACK_COLOR = 0x374151;
const EDGE_COLOR = 0x94a3b8;
const SCALE = 0.012;
const TRACK_WIDTH = 7.5;
const TRAIL_POINTS = 22;

/**
 * Ported from prototype_3d/index.html.
 * Accepts `payload` (the full 3D telemetry JSON) and `waypointIdx` from the parent.
 */
export default function TrackMap3D({ payload, waypointIdx = 0, playing = false, onFrameAdvance }) {
  const containerRef = useRef(null);
  const stateRef = useRef(null);
  const [cameraMode, setCameraMode] = useState("follow");
  const [speedMultiplier, setSpeedMultiplier] = useState(1);

  /* ── Initialise Three.js scene (once) ──────────────────────── */
  useEffect(() => {
    const container = containerRef.current;
    if (!container || stateRef.current) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x070b14, 1);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x070b14, 80, 360);

    const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 1200);
    camera.position.set(0, 72, 110);

    scene.add(new THREE.AmbientLight(0xffffff, 0.76));
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(55, 90, 30);
    scene.add(sun);

    const grid = new THREE.GridHelper(420, 42, 0x243047, 0x172033);
    grid.position.y = -0.08;
    scene.add(grid);

    const trackGroup = new THREE.Group();
    scene.add(trackGroup);

    const driver1 = createCar(DRIVER1_COLOR);
    const driver2 = createCar(DRIVER2_COLOR);
    scene.add(driver1, driver2);

    const driver1Trail = createTrail(DRIVER1_COLOR);
    const driver2Trail = createTrail(DRIVER2_COLOR);
    scene.add(driver1Trail, driver2Trail);

    /* Handle resizing */
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    ro.observe(container);
    renderer.setSize(container.clientWidth, container.clientHeight);
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();

    stateRef.current = {
      renderer,
      scene,
      camera,
      trackGroup,
      driver1,
      driver2,
      driver1Trail,
      driver2Trail,
      normalized: [],
      orbitAngle: 0,
      ro,
    };

    /* Render loop */
    let animId;
    const loop = () => {
      renderer.render(scene, camera);
      animId = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
      renderer.dispose();
      container.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  /* ── Rebuild track when payload changes ────────────────────── */
  useEffect(() => {
    const s = stateRef.current;
    if (!s || !payload || !payload.points || payload.points.length < 2) return;

    const normalized = normalizePoints(payload.points);
    s.normalized = normalized;
    rebuildTrack(s.trackGroup, normalized);
    updateFrame(s, 0, cameraMode);
  }, [payload]);

  /* ── Update frame when waypointIdx changes ─────────────────── */
  useEffect(() => {
    const s = stateRef.current;
    if (!s || !s.normalized.length) return;
    const idx = Math.min(waypointIdx, s.normalized.length - 1);
    updateFrame(s, idx, cameraMode);
  }, [waypointIdx, cameraMode]);

  /* ── Playback animation loop ───────────────────────────────── */
  useEffect(() => {
    const s = stateRef.current;
    if (!s || !playing || !s.normalized.length) return;

    let lastTime = performance.now();
    let exactFrame = waypointIdx;
    let lastIntFrame = waypointIdx;
    let animId;

    const tick = (now) => {
      const elapsed = now - lastTime;
      lastTime = now;
      
      // Accumulate fractional frames
      exactFrame += (elapsed / 95) * speedMultiplier;
      const currentIntFrame = Math.floor(exactFrame) % s.normalized.length;
      
      // Always update frame to ensure smooth camera orbit
      updateFrame(s, currentIntFrame, cameraMode);
      
      // Only fire state updates when we cross an integer frame boundary
      if (currentIntFrame !== lastIntFrame) {
        lastIntFrame = currentIntFrame;
        if (onFrameAdvance) onFrameAdvance(currentIntFrame);
      }
      
      animId = requestAnimationFrame(tick);
    };
    animId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animId);
  }, [playing, speedMultiplier, cameraMode, onFrameAdvance]);

  return (
    <div className="track-3d-container" ref={containerRef}>
      <div className="track-3d-toolbar">
        <select
          value={cameraMode}
          onChange={(e) => setCameraMode(e.target.value)}
          aria-label="Camera mode"
        >
          <option value="follow">Follow</option>
          <option value="chase">Chase</option>
          <option value="orbit">Orbit</option>
        </select>
        <select
          value={speedMultiplier}
          onChange={(e) => setSpeedMultiplier(Number(e.target.value))}
          aria-label="Playback speed"
        >
          <option value={0.25}>0.25×</option>
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={1.5}>1.5×</option>
          <option value={2}>2×</option>
        </select>
      </div>
    </div>
  );
}

/* ── Helpers (ported from prototype) ─────────────────────────── */

function normalizePoints(source) {
  const coords = source.flatMap((p) => [
    [p.driver1.x, p.driver1.y],
    [p.driver2.x, p.driver2.y],
  ]);
  const centerX = average(coords.map((c) => c[0]));
  const centerY = average(coords.map((c) => c[1]));

  return source.map((p) => ({
    ...p,
    driver1Position: toVector(p.driver1.x, p.driver1.y, centerX, centerY),
    driver2Position: toVector(p.driver2.x, p.driver2.y, centerX, centerY),
  }));
}

function rebuildTrack(trackGroup, normalized) {
  trackGroup.clear();
  const ribbon = createTrackRibbon(normalized);
  const centerLine = createLine(
    normalized.map((p) => midpoint(p.driver1Position, p.driver2Position)),
    EDGE_COLOR,
    0.55
  );
  trackGroup.add(ribbon, centerLine);
}

function createTrackRibbon(trackPoints) {
  const vertices = [];
  const indices = [];
  const centers = trackPoints.map((p) =>
    midpoint(p.driver1Position, p.driver2Position)
  );

  centers.forEach((center, i) => {
    const prev = centers[Math.max(0, i - 1)];
    const next = centers[Math.min(centers.length - 1, i + 1)];
    const tangent = new THREE.Vector3().subVectors(next, prev).normalize();
    const normal = new THREE.Vector3(-tangent.z, 0, tangent.x)
      .normalize()
      .multiplyScalar(TRACK_WIDTH);
    const left = new THREE.Vector3().addVectors(center, normal);
    const right = new THREE.Vector3().subVectors(center, normal);
    vertices.push(left.x, 0, left.z, right.x, 0, right.z);
  });

  for (let i = 0; i < centers.length - 1; i++) {
    const a = i * 2;
    indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(vertices, 3)
  );
  geometry.setIndex(indices);
  geometry.computeVertexNormals();

  return new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: TRACK_COLOR,
      roughness: 0.86,
      metalness: 0.04,
      side: THREE.DoubleSide,
    })
  );
}

function createCar(color) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(3.2, 0.9, 5.4),
    new THREE.MeshStandardMaterial({ color, roughness: 0.46, metalness: 0.22 })
  );
  body.position.y = 0.75;

  const nose = new THREE.Mesh(
    new THREE.ConeGeometry(1.2, 2.4, 4),
    new THREE.MeshStandardMaterial({ color, roughness: 0.52, metalness: 0.18 })
  );
  nose.position.set(0, 0.75, -3.6);
  nose.rotation.y = Math.PI / 4;
  nose.rotation.x = Math.PI / 2;

  group.add(body, nose);
  return group;
}

function createTrail(color) {
  return createLine([], color, 0.82);
}

function createLine(pts, color, opacity) {
  const geometry = new THREE.BufferGeometry().setFromPoints(pts);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
  });
  return new THREE.Line(geometry, material);
}

function updateFrame(state, index, cameraMode) {
  const { normalized, driver1, driver2, driver1Trail, driver2Trail, camera } = state;
  if (!normalized.length) return;

  const point = normalized[index];
  positionCar(driver1, point.driver1Position, headingAt(normalized, index, "driver1Position"));
  positionCar(driver2, point.driver2Position, headingAt(normalized, index, "driver2Position"));
  updateTrail(driver1Trail, normalized, index, "driver1Position");
  updateTrail(driver2Trail, normalized, index, "driver2Position");
  updateCamera(state, index, cameraMode);
}

function positionCar(car, position, heading) {
  car.position.copy(position);
  car.rotation.set(0, heading, 0);
}

function headingAt(normalized, index, key) {
  const prev = normalized[Math.max(0, index - 1)]?.[key];
  const next = normalized[Math.min(normalized.length - 1, index + 1)]?.[key];
  if (!prev || !next) return 0;
  return Math.atan2(next.x - prev.x, next.z - prev.z);
}

function updateTrail(line, normalized, index, key) {
  const start = Math.max(0, index - TRAIL_POINTS);
  const trail = normalized.slice(start, index + 1).map((p) => p[key]);
  line.geometry.dispose();
  line.geometry = new THREE.BufferGeometry().setFromPoints(trail);
}

function updateCamera(state, index, cameraMode) {
  const { normalized, camera } = state;
  const current = normalized[index];
  const center = midpoint(current.driver1Position, current.driver2Position);

  if (cameraMode === "orbit") {
    state.orbitAngle += 0.006;
    camera.position.set(
      center.x + Math.sin(state.orbitAngle) * 95,
      78,
      center.z + Math.cos(state.orbitAngle) * 95
    );
    camera.lookAt(center.x, 0, center.z);
    return;
  }

  const heading = headingAt(normalized, index, "driver1Position");
  const back = new THREE.Vector3(Math.sin(heading), 0, Math.cos(heading));
  const dist = cameraMode === "chase" ? 34 : 58;
  const height = cameraMode === "chase" ? 15 : 42;
  const target = new THREE.Vector3()
    .copy(center)
    .add(back.multiplyScalar(dist));
  target.y = height;
  camera.position.lerp(target, 0.16);
  camera.lookAt(center.x, 1.5, center.z);
}

function toVector(x, y, centerX, centerY) {
  return new THREE.Vector3(
    (x - centerX) * SCALE,
    0.35,
    (y - centerY) * SCALE
  );
}

function midpoint(a, b) {
  return new THREE.Vector3((a.x + b.x) / 2, 0, (a.z + b.z) / 2);
}

function average(values) {
  return values.reduce((s, v) => s + v, 0) / values.length;
}
