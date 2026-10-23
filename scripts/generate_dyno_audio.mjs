import fs from "node:fs";

// Gerador de áudio sintético procedural para dinamômetro e quebra de motor (PCM 16-bit mono 44.1 kHz)
export function generateDynoSoundtrack(outputPath, events) {
  const sampleRate = 44100;
  const totalDuration = events.totalDuration || 52; // segundos
  const numSamples = Math.floor(sampleRate * totalDuration);
  const buffer = Buffer.alloc(44 + numSamples * 2);

  // RIFF header
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + numSamples * 2, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16); // subchunk1 size
  buffer.writeUInt16LE(1, 20);  // PCM format
  buffer.writeUInt16LE(1, 22);  // mono
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28); // byte rate
  buffer.writeUInt16LE(2, 32);  // block align
  buffer.writeUInt16LE(16, 34); // bits per sample
  buffer.write("data", 36);
  buffer.writeUInt32LE(numSamples * 2, 40);

  // Síntese de áudio amostra por amostra
  let phaseEngine = 0;
  let phaseTurbo = 0;
  let phaseAlarm = 0;

  for (let i = 0; i < numSamples; i++) {
    const t = i / sampleRate;
    let sample = 0;

    // --- Puxada 1 (0s até 21s) ---
    if (t < 21) {
      let rpm = 1200;
      let throttle = 0.2;
      let boost = 0.1;

      if (t >= 3 && t < 17) {
        // Rampa de 1200 a 6500 RPM
        const p = (t - 3) / 14;
        rpm = 1200 + (6500 - 1200) * Math.pow(p, 1.1);
        throttle = 1.0;
        boost = 0.3 + 0.9 * p;
      } else if (t >= 17) {
        // Desaceleração
        const p = (t - 17) / 4;
        rpm = 6500 - (6500 - 1200) * p;
        throttle = 0.05;
        boost = 0.0;
      }

      // Frequência de combustão de 4 cilindros: (RPM / 60) * 2
      const fComb = (rpm / 60) * 2;
      phaseEngine += (2 * Math.PI * fComb) / sampleRate;
      
      // Harmônicos do motor (ronco encorpado)
      const h1 = Math.sin(phaseEngine);
      const h2 = Math.sin(phaseEngine * 2) * 0.6;
      const h3 = Math.sin(phaseEngine * 3) * 0.35;
      const h4 = Math.sin(phaseEngine * 4) * 0.2;
      const sub = Math.sin(phaseEngine * 0.5) * 0.4;
      const engineTone = (h1 + h2 + h3 + h4 + sub) / 2.5;

      // Turbo spool (assobio que sobe de 1800 Hz a 4200 Hz)
      const fTurbo = 1500 + boost * 2800;
      phaseTurbo += (2 * Math.PI * fTurbo) / sampleRate;
      const turboWhistle = Math.sin(phaseTurbo) * (boost * 0.22);

      // Sopro de ar / exaustão (ruído filtrado)
      const whiteNoise = (Math.random() * 2 - 1) * (0.08 + throttle * 0.18);

      // Blow-off valve no corte (t ~ 17s)
      let bov = 0;
      if (t >= 17.0 && t <= 18.2) {
        const bp = (t - 17.0) / 1.2;
        bov = (Math.random() * 2 - 1) * Math.exp(-bp * 4) * 0.4;
      }

      sample = engineTone * (0.35 + throttle * 0.45) + turboWhistle + whiteNoise + bov;
    }

    // --- Intervalo ECU / Live Tune (21s até 29s) ---
    else if (t >= 21 && t < 29) {
      // Motor em marcha lenta suave de fundo + cliques de interface
      const rpm = 1000;
      const fComb = (rpm / 60) * 2;
      phaseEngine += (2 * Math.PI * fComb) / sampleRate;
      const idle = (Math.sin(phaseEngine) + Math.sin(phaseEngine * 2) * 0.4) * 0.12;
      
      // Cliques da UI
      let click = 0;
      [22.5, 24.2, 26.0, 27.5].forEach(ct => {
        if (Math.abs(t - ct) < 0.02) {
          click = Math.sin(2 * Math.PI * 1800 * (t - ct)) * 0.25;
        }
      });
      sample = idle + click;
    }

    // --- Puxada 2 com Quebra de Motor (29s em diante) ---
    else if (t >= 29) {
      const failTime = events.failTime || 38.5; // instante da explosão

      if (t < failTime) {
        // Rampa agressiva com ponto excessivo (mais áspero e agressivo)
        const p = (t - 29) / (failTime - 29);
        const rpm = 1200 + (5200 - 1200) * p;
        const fComb = (rpm / 60) * 2;
        phaseEngine += (2 * Math.PI * fComb) / sampleRate;

        // Ronco mais estridente e áspero
        const engineTone = (Math.sin(phaseEngine) + Math.sin(phaseEngine * 2) * 0.8 + Math.sin(phaseEngine * 3) * 0.5) * 0.65;
        
        // Turbo assobiando muito alto (overboost)
        const fTurbo = 2000 + p * 3500;
        phaseTurbo += (2 * Math.PI * fTurbo) / sampleRate;
        const turboWhistle = Math.sin(phaseTurbo) * (0.2 + p * 0.3);

        // Pré-detonação / Knock pinging logo antes de quebrar (último 1.5s)
        let knock = 0;
        if (t > failTime - 1.8) {
          const kp = (t - (failTime - 1.8)) / 1.8;
          // Cliques metálicos agudos a 6.5 kHz
          if (Math.sin(t * 85) > 0.7) {
            knock = (Math.random() * 2 - 1) * Math.sin(2 * Math.PI * 6500 * t) * (0.3 + kp * 0.5);
          }
        }

        sample = engineTone + turboWhistle + knock;
      }
      // Instante do estouro / Quebra catastrófica (duração de 1.2s)
      else if (t >= failTime && t < failTime + 1.5) {
        const dt = t - failTime;
        // Impacto metálico pesado (explosão de pistão / biela quebrada)
        const boom = Math.sin(2 * Math.PI * 65 * dt) * Math.exp(-dt * 4) * 0.95;
        const metalCrack = (Math.random() * 2 - 1) * Math.exp(-dt * 6) * 0.8;
        const hiss = (Math.random() * 2 - 1) * Math.exp(-dt * 2) * 0.3;
        sample = boom + metalCrack + hiss;
      }
      // Pós-quebra: Motor morto + Alarme de emergência (Laudo Forense na tela)
      else {
        // Alarme intermitente (880 Hz / bip-bip)
        phaseAlarm += (2 * Math.PI * 880) / sampleRate;
        const isBeep = (t % 0.8) < 0.4;
        const alarm = isBeep ? Math.sin(phaseAlarm) * 0.28 : 0;
        const hiss = (Math.random() * 2 - 1) * 0.03; // vapor do radiador
        sample = alarm + hiss;
      }
    }

    // Normalização e conversão para 16-bit signed integer (-32768 a 32767)
    sample = Math.max(-0.95, Math.min(0.95, sample));
    const intSample = Math.floor(sample * 32767);
    buffer.writeInt16LE(intSample, 44 + i * 2);
  }

  fs.writeFileSync(outputPath, buffer);
  console.log(`Audio WAV gerado com sucesso: ${outputPath} (${totalDuration}s)`);
}

// Se executado diretamente
if (process.argv[1]?.endsWith("generate_dyno_audio.mjs")) {
  generateDynoSoundtrack("docs/videos/dyno_soundtrack.wav", { totalDuration: 54, failTime: 38.5 });
}
