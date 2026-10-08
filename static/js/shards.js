(function () {
  const canvas = document.getElementById("shards-bg");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  let width, height, dpr;
  let shards = [];
  let mouse = { x: -9999, y: -9999, active: false };

  const SHARD_COUNT = 46;
  const INTERACTION_RADIUS = 140;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function rand(min, max) {
    return Math.random() * (max - min) + min;
  }

  function makeShard() {
    const len = rand(18, 48);
    return {
      x: rand(0, width),
      y: rand(0, height),
      len,
      width: rand(2, 5),
      angle: rand(0, Math.PI * 2),
      drift: rand(-0.15, 0.15),
      speed: rand(0.15, 0.5),
      dir: rand(0, Math.PI * 2),
      opacity: rand(0.05, 0.22),
      phase: rand(0, Math.PI * 2),
      vx: 0,
      vy: 0,
    };
  }

  function init() {
    resize();
    shards = Array.from({ length: SHARD_COUNT }, makeShard);
  }

  function step(time) {
    ctx.clearRect(0, 0, width, height);

    for (const s of shards) {
      // gentle flowing drift, diagonal stream
      const flowX = Math.cos(s.dir) * s.speed;
      const flowY = Math.sin(s.dir) * s.speed + 0.12;
      const wobble = Math.sin(time * 0.0004 + s.phase) * 0.08;

      let vx = flowX + wobble;
      let vy = flowY;

      if (mouse.active) {
        const dx = s.x - mouse.x;
        const dy = s.y - mouse.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < INTERACTION_RADIUS && dist > 0.01) {
          const force = (1 - dist / INTERACTION_RADIUS) * 0.6;
          vx += (dx / dist) * force;
          vy += (dy / dist) * force;
        }
      }

      s.x += vx;
      s.y += vy;
      s.angle += s.drift * 0.01;

      if (s.x < -60) s.x = width + 60;
      if (s.x > width + 60) s.x = -60;
      if (s.y < -60) s.y = height + 60;
      if (s.y > height + 60) s.y = -60;

      ctx.save();
      ctx.translate(s.x, s.y);
      ctx.rotate(s.angle);
      ctx.shadowColor = "rgba(255, 255, 255, 0.35)";
      ctx.shadowBlur = 8;
      ctx.strokeStyle = `rgba(237, 237, 237, ${s.opacity})`;
      ctx.lineWidth = s.width;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(-s.len / 2, 0);
      ctx.lineTo(s.len / 2, 0);
      ctx.stroke();
      ctx.restore();
    }

    if (!prefersReducedMotion) {
      requestAnimationFrame(step);
    }
  }

  window.addEventListener("resize", resize);
  window.addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    mouse.active = true;
  });
  window.addEventListener("mouseleave", () => {
    mouse.active = false;
  });

  init();
  if (prefersReducedMotion) {
    step(0);
  } else {
    requestAnimationFrame(step);
  }
})();
