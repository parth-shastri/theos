(function () {
  const NS = 'http://www.w3.org/2000/svg';
  function draw() {
    document.querySelectorAll('.flow').forEach(function (root, fi) {
      const mk = 'ah' + fi;
      const edges = JSON.parse(root.dataset.edges);
      const R = root.getBoundingClientRect();
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('class', 'edges');
      svg.setAttribute('width', R.width);
      svg.setAttribute('height', R.height);
      svg.innerHTML = '<defs><marker id="' + mk + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1 L10,5 L0,9 z" fill="#070707"/></marker></defs>';
      root.appendChild(svg);
      const rect = function (id) {
        const r = document.getElementById(id).getBoundingClientRect();
        return { l: r.left - R.left, t: r.top - R.top, r: r.right - R.left, b: r.bottom - R.top,
                 cx: (r.left + r.right) / 2 - R.left, cy: (r.top + r.bottom) / 2 - R.top };
      };
      edges.sort(function (x, y) { return (y.dash ? 1 : 0) - (x.dash ? 1 : 0); });
      edges.forEach(function (e) {
        const a = rect(e.from), b = rect(e.to);
        let d, lx, ly, side = false;
        if (b.t >= a.b - 1) {
          const x1 = e.fx === 'align' ? Math.min(Math.max(b.cx, a.l + 10), a.r - 10) : a.cx;
          const y1 = a.b, x2 = b.cx, y2 = b.t - 1, my = (y1 + y2) / 2;
          const straight = Math.abs(x1 - x2) < 1;
          d = straight ? `M${x1},${y1} V${y2}` : `M${x1},${y1} V${my} H${x2} V${y2}`;
          if (e.lp === 'end') { lx = x2; ly = y2 - 11; }
          else if (e.lp === 'side') { lx = x2 + 6; ly = (my + y2) / 2; side = true; }
          else { lx = straight ? x1 : (x1 + x2) / 2; ly = straight ? (y1 + y2) / 2 : my; }
        } else if (b.l >= a.r - 1) {
          const x1 = a.r, y1 = a.cy, x2 = b.l - 1;
          const y2 = (a.cy > b.t + 4 && a.cy < b.b - 4) ? a.cy : b.cy;
          const mx = e.mx === 'gap' ? x2 - 16 : (x1 + x2) / 2;
          d = Math.abs(y1 - y2) < 1 ? `M${x1},${y1} H${x2}` : `M${x1},${y1} H${mx} V${y2} H${x2}`;
          lx = (x1 + x2) / 2; ly = y1 - 10;
        } else {
          d = `M${a.cx},${a.cy} L${b.cx},${b.cy}`;
          lx = (a.cx + b.cx) / 2; ly = (a.cy + b.cy) / 2;
        }
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', d);
        p.setAttribute('fill', 'none');
        p.setAttribute('stroke', '#070707');
        p.setAttribute('stroke-width', '1.2');
        if (e.dash) p.setAttribute('stroke-dasharray', '4 3');
        p.setAttribute('marker-end', 'url(#' + mk + ')');
        if (e.both) p.setAttribute('marker-start', 'url(#' + mk + ')');
        svg.appendChild(p);
        if (e.label) {
          const l = document.createElement('div');
          l.className = 'elbl' + (side ? ' side' : '');
          l.textContent = e.label;
          l.style.left = lx + 'px';
          l.style.top = ly + 'px';
          root.appendChild(l);
        }
      });
    });
    document.body.classList.add('drawn');
  }
  document.fonts.ready.then(draw);
})();
