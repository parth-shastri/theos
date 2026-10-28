export default function VoiceAmbience({ agentName }) {
  return (
    <>
      <div id="voice-ambience" aria-hidden="true">
        <svg
          viewBox="0 0 1440 320"
          preserveAspectRatio="none"
          focusable="false"
        >
          <path
            className="voice-wave wave-back"
            d="M-300 190C-60 85 180 265 420 170S900 70 1140 175 1620 245 1860 150V440H-300Z"
          />
          <path
            className="voice-wave wave-middle"
            d="M-300 210C-60 285 180 100 420 190S900 280 1140 180 1620 110 1860 230V440H-300Z"
          />
          <path
            className="voice-wave wave-front"
            d="M-300 245C-60 150 180 300 420 235S900 160 1140 250 1620 285 1860 205V440H-300Z"
          />
        </svg>
      </div>
    </>
  );
}
