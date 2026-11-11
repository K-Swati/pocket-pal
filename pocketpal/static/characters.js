// Pocket Pal's characters. All original designs, drawn on a 200x200 canvas.
// Every character shares the same face (eyes, cheeks, mouth, brows) so expressions and lip sync work for all.
// Each character has its own fixed signature colours (BRAND below). They never change with the app theme,
// so a character always looks the same everywhere: keep these values in sync with any brand/trademark assets.

(function () {
  const BODY = 'url(#__G__)';
  const BLOB = 'M100 30 C152 30 174 72 174 116 C174 162 142 180 100 180 C58 180 26 162 26 116 C26 72 48 30 100 30Z';
  const ROUND = 'M100 40 C156 40 176 78 176 118 C176 162 144 180 100 180 C56 180 24 162 24 118 C24 78 44 40 100 40Z';
  const SQUAT = 'M100 50 C152 50 175 84 175 122 C175 164 142 182 100 182 C58 182 25 164 25 122 C25 84 48 50 100 50Z';
  const arms = (y = 128, fill = 'var(--char2)') =>
    `<ellipse data-id="armL" cx="34" cy="${y}" rx="12" ry="9" style="fill:${fill}"/><ellipse data-id="armR" cx="166" cy="${y}" rx="12" ry="9" style="fill:${fill}"/>`;
  const shine = `<ellipse cx="74" cy="66" rx="20" ry="10" fill="#fff" opacity=".35" transform="rotate(-25 74 66)"/>`;
  const feet = `<ellipse cx="72" cy="178" rx="17" ry="8" style="fill:var(--char2)"/><ellipse cx="128" cy="178" rx="17" ry="8" style="fill:var(--char2)"/>`;

  // Signature colours: light (highlight side), main body, eyes. The face colours are shared by all characters.
  const BRAND = {
    mochi:  {light: '#ffe3ea', main: '#f59ab5'},   // strawberry mochi pink
    miso:   {light: '#ffe2bd', main: '#f39a4c'},   // ginger tabby orange
    bao:    {light: '#f0d3b3', main: '#b57d52'},   // honey bear brown
    clover: {light: '#f3efff', main: '#ab97ee'},   // pale lavender
    nimbus: {light: '#ffffff', main: '#8ccbf2'},   // sky blue
  };
  const EYE = '#2b2440';

  const CHARACTERS = {
    mochi: {
      name: 'Mochi', kind: 'a soft little blob with a leaf sprout',
      back: `<g data-id="sprout"><path d="M100 34 C100 24 101 18 103 12" stroke="#5fbf72" stroke-width="4" fill="none" stroke-linecap="round"/>
        <path d="M103 14 C112 4 126 6 128 12 C120 20 108 20 103 14Z" fill="#7ad48a"/><path d="M101 18 C92 10 80 12 79 18 C86 24 96 23 101 18Z" fill="#8fe09d"/></g>` + arms(),
      body: `<path d="${BLOB}" fill="${BODY}"/>` + shine,
      front: '',
    },
    miso: {
      name: 'Miso', kind: 'a round, cuddly kitten',
      back: `<path data-id="tail" d="M146 168 C196 172 206 116 184 92" stroke="var(--char2)" stroke-width="14" fill="none" stroke-linecap="round"/>
        <g data-id="ears"><path d="M40 92 Q34 34 56 22 Q74 32 98 56 Z" style="fill:var(--char2)"/><path d="M52 78 Q50 44 60 38 Q70 46 84 60 Z" fill="#ffb3c7"/>
        <path d="M160 92 Q166 34 144 22 Q126 32 102 56 Z" style="fill:var(--char2)"/><path d="M148 78 Q150 44 140 38 Q130 46 116 60 Z" fill="#ffb3c7"/></g>` + arms(134),
      body: `<path d="${ROUND}" fill="${BODY}"/>` + shine,
      front: `<path d="M94 119 Q100 115 106 119 Q100 126 94 119Z" fill="#ff8fab"/>
        <g stroke="var(--eye)" stroke-width="2" stroke-linecap="round" opacity=".45"><path d="M24 120 L48 124"/><path d="M24 132 L48 131"/><path d="M176 120 L152 124"/><path d="M176 132 L152 131"/></g>`,
    },
    bao: {
      name: 'Bao', kind: 'a gentle bear cub',
      back: `<g data-id="ears"><circle cx="50" cy="56" r="24" style="fill:var(--char2)"/><circle cx="50" cy="56" r="12" fill="#fff" opacity=".45"/>
        <circle cx="150" cy="56" r="24" style="fill:var(--char2)"/><circle cx="150" cy="56" r="12" fill="#fff" opacity=".45"/></g>` + arms(134),
      body: `<path d="${ROUND}" fill="${BODY}"/>` + shine + feet,
      front: `<ellipse cx="100" cy="133" rx="31" ry="21" fill="#fff" opacity=".5"/><ellipse cx="100" cy="121" rx="8.5" ry="6" style="fill:var(--eye)"/>`,
    },
    clover: {
      name: 'Clover', kind: 'a sweet bunny with one floppy ear',
      back: `<g data-id="earL"><ellipse cx="70" cy="34" rx="15" ry="42" style="fill:var(--char2)"/><ellipse cx="70" cy="38" rx="7" ry="30" fill="#ffc4d6"/></g>
        <g data-id="earR"><ellipse cx="130" cy="34" rx="15" ry="42" style="fill:var(--char2)"/><ellipse cx="130" cy="38" rx="7" ry="30" fill="#ffc4d6"/></g>` + arms(136),
      body: `<path d="${SQUAT}" fill="${BODY}"/>` + shine + feet,
      front: `<path d="M95 120 Q100 116 105 120 Q100 125 95 120Z" fill="#ff8fab"/><rect x="95" y="139" width="10" height="7" rx="2" fill="#fff" data-id="teeth"/>`,
    },
    nimbus: {
      name: 'Nimbus', kind: 'a fluffy little cloud',
      back: arms(140, 'var(--char1)'),
      body: `<g fill="${BODY}"><circle cx="66" cy="104" r="42"/><circle cx="134" cy="104" r="42"/><circle cx="100" cy="80" r="50"/>
        <circle cx="44" cy="138" r="32"/><circle cx="156" cy="138" r="32"/><ellipse cx="100" cy="146" rx="66" ry="36"/></g>
        <circle cx="76" cy="62" r="13" fill="#fff" opacity=".45"/><circle cx="98" cy="50" r="8" fill="#fff" opacity=".35"/>`,
      front: '',
    },
  };

  const FACE = `
    <g data-id="face">
      <g class="brows" stroke="var(--eye)" stroke-width="3.5" stroke-linecap="round" fill="none">
        <path d="M61 88 Q72 85 83 79"/><path d="M117 79 Q128 85 139 88"/></g>
      <g class="eye eye-open"><ellipse cx="74" cy="106" rx="11" ry="14" style="fill:var(--eye)"/><circle cx="70" cy="100" r="4.5" fill="#fff"/><circle cx="78" cy="112" r="2" fill="#fff" opacity=".8"/></g>
      <g class="eye eye-open"><ellipse cx="126" cy="106" rx="11" ry="14" style="fill:var(--eye)"/><circle cx="122" cy="100" r="4.5" fill="#fff"/><circle cx="130" cy="112" r="2" fill="#fff" opacity=".8"/></g>
      <g class="eye-happy" stroke="var(--eye)" stroke-width="5" stroke-linecap="round" fill="none"><path d="M63 108 Q74 94 85 108"/><path d="M115 108 Q126 94 137 108"/></g>
      <ellipse cx="54" cy="130" rx="12" ry="7" fill="#ff7fa3" opacity=".5"/><ellipse cx="146" cy="130" rx="12" ry="7" fill="#ff7fa3" opacity=".5"/>
      <path data-id="smile" d="M89 131 Q100 143 111 131" stroke="var(--eye)" stroke-width="4" fill="none" stroke-linecap="round"/>
      <g data-id="mouthO" style="display:none"><ellipse data-id="mouthShape" cx="100" cy="135" rx="9" ry="5" fill="#6b2d3c"/><ellipse data-id="tongue" cx="100" cy="139" rx="5" ry="2.5" fill="#ff8fa6"/></g>
    </g>`;

  let n = 0;
  // main=true gives the parts real ids (used by animations and lip sync); thumbnails get none, so ids stay unique.
  function characterSVG(key, main) {
    const c = CHARACTERS[key] || CHARACTERS.mochi, g = 'g' + (++n);
    const b = BRAND[key] || BRAND.mochi;
    // Local custom properties override the theme's, so the character's colours are fixed.
    let svg = `<svg viewBox="0 0 200 200" aria-hidden="true" data-char="${key}" style="--char1:${b.light};--char2:${b.main};--eye:${EYE}">
      <defs><radialGradient id="${g}" gradientUnits="userSpaceOnUse" cx="76" cy="66" r="150">
        <stop offset="0%" stop-color="#fff" stop-opacity=".9"/><stop offset="16%" style="stop-color:var(--char1)"/><stop offset="100%" style="stop-color:var(--char2)"/>
      </radialGradient></defs>
      <ellipse data-id="shadow" cx="100" cy="188" rx="52" ry="8" fill="#000" opacity=".1"/>
      <g data-id="bodyGroup">${c.back}${c.body}${c.front}${FACE}</g>
      ${main ? `<g data-id="dots" style="fill:var(--accent)"><circle cx="158" cy="44" r="5"/><circle cx="172" cy="34" r="6"/><circle cx="188" cy="22" r="7"/></g>` : ''}
    </svg>`;
    svg = svg.replace(/__G__/g, g);
    return main ? svg.replace(/data-id="/g, 'id="') : svg.replace(/ data-id="[^"]*"/g, '');
  }

  Object.keys(CHARACTERS).forEach(k => { CHARACTERS[k].colors = BRAND[k]; });
  window.CHARACTERS = CHARACTERS;
  window.characterSVG = characterSVG;
})();
