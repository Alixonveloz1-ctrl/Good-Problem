/**
 * Grabar voz en el iPhone y entregarla como la quiere Chirp.
 *
 * Chirp pide WAV sin comprimir, 16 bits, un solo canal, 24.000 muestras por
 * segundo. Safari graba en el formato que le da la gana, asi que aqui se
 * decodifica lo grabado y se vuelve a escribir en ese formato exacto.
 */

export interface Grabacion {
  blob: Blob
  segundos: number
}

export function grabacionDisponible(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  )
}

export class Grabadora {
  private recorder: MediaRecorder | null = null
  private trozos: Blob[] = []
  private stream: MediaStream | null = null
  private inicio = 0

  async empezar(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false },
    })
    this.trozos = []
    this.recorder = new MediaRecorder(this.stream)
    this.recorder.ondataavailable = (evento) => {
      if (evento.data.size > 0) this.trozos.push(evento.data)
    }
    this.inicio = performance.now()
    this.recorder.start()
  }

  parar(): Promise<Grabacion> {
    return new Promise((resolve, reject) => {
      const recorder = this.recorder
      if (!recorder) {
        reject(new Error('No hay ninguna grabacion en marcha.'))
        return
      }
      recorder.onstop = () => {
        const segundos = (performance.now() - this.inicio) / 1000
        this.stream?.getTracks().forEach((pista) => pista.stop())
        this.stream = null
        this.recorder = null
        resolve({ blob: new Blob(this.trozos, { type: recorder.mimeType }), segundos })
      }
      recorder.stop()
    })
  }

  get grabando(): boolean {
    return this.recorder?.state === 'recording'
  }
}

const FRECUENCIA = 24000

/** Decodifica lo grabado, lo pasa a un canal a 24 kHz y escribe el WAV. */
export async function aWav24k(blob: Blob): Promise<Uint8Array> {
  const bytes = await blob.arrayBuffer()
  const AudioCtx: typeof AudioContext =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  const contexto = new AudioCtx()
  let decodificado: AudioBuffer
  try {
    decodificado = await contexto.decodeAudioData(bytes.slice(0))
  } finally {
    void contexto.close()
  }

  const muestras = Math.ceil(decodificado.duration * FRECUENCIA)
  const offline = new OfflineAudioContext(1, muestras, FRECUENCIA)
  const fuente = offline.createBufferSource()
  fuente.buffer = decodificado
  fuente.connect(offline.destination)
  fuente.start()
  const remuestreado = await offline.startRendering()

  return escribirWav(remuestreado.getChannelData(0), FRECUENCIA)
}

function escribirWav(muestras: Float32Array, frecuencia: number): Uint8Array {
  const buffer = new ArrayBuffer(44 + muestras.length * 2)
  const vista = new DataView(buffer)

  const texto = (posicion: number, valor: string) => {
    for (let i = 0; i < valor.length; i += 1) vista.setUint8(posicion + i, valor.charCodeAt(i))
  }

  texto(0, 'RIFF')
  vista.setUint32(4, 36 + muestras.length * 2, true)
  texto(8, 'WAVE')
  texto(12, 'fmt ')
  vista.setUint32(16, 16, true)
  vista.setUint16(20, 1, true) // PCM sin comprimir
  vista.setUint16(22, 1, true) // un canal
  vista.setUint32(24, frecuencia, true)
  vista.setUint32(28, frecuencia * 2, true)
  vista.setUint16(32, 2, true)
  vista.setUint16(34, 16, true) // 16 bits
  texto(36, 'data')
  vista.setUint32(40, muestras.length * 2, true)

  let posicion = 44
  for (let i = 0; i < muestras.length; i += 1) {
    const valor = Math.max(-1, Math.min(1, muestras[i]))
    vista.setInt16(posicion, valor < 0 ? valor * 0x8000 : valor * 0x7fff, true)
    posicion += 2
  }
  return new Uint8Array(buffer)
}

export function aBase64(bytes: Uint8Array): string {
  let binario = ''
  const trozo = 0x8000
  for (let i = 0; i < bytes.length; i += trozo) {
    binario += String.fromCharCode(...bytes.subarray(i, i + trozo))
  }
  return btoa(binario)
}

export function urlDeReproduccion(bytes: Uint8Array): string {
  return URL.createObjectURL(new Blob([bytes.slice().buffer as ArrayBuffer], { type: 'audio/wav' }))
}
