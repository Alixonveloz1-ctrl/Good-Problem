import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, newIdempotencyKey } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import type { ProductionPlan, Scene, VideoProject } from '../api/types'
import { JobWatcher } from '../components/JobWatcher'
import { ModelPicker, type ModelChoice } from '../components/ModelPicker'
import {
  Card,
  DeleteButton,
  Empty,
  ErrorNote,
  Loading,
  Sheet,
  StatusBadge,
  TopBar,
} from '../components/ui'

export function ProjectsScreen() {
  const { universeId = '' } = useParams()
  const { data, loading, error, reload } = useResource<VideoProject[]>(
    `/api/universes/${universeId}/video-projects`,
  )
  const action = useAction()

  return (
    <>
      <TopBar title="Videoclips" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error} onDismiss={action.clearError} />
        <ErrorNote error={action.error} onDismiss={action.clearError} />
        {data && data.length === 0 && (
          <Empty
            title="Sin videoclips"
            hint="Un videoclip arranca desde una cancion aprobada, en la pantalla de la cancion."
          />
        )}
        <div className="list">
          {(data ?? []).map((project) => (
            <div key={project.id} className="card fila-borrable">
              <Link to={`/u/${universeId}/projects/${project.id}`} className="grow">
                <div className="row between">
                  <strong>{project.title || 'Sin titulo'}</strong>
                  <StatusBadge status={project.status} />
                </div>
                <div className="muted">{project.video_type}</div>
              </Link>
              <DeleteButton
                busy={action.busy}
                onDelete={async () => {
                  await action.run(() =>
                    api.del(`/api/universes/${universeId}/video-projects/${project.id}`),
                  )
                  await reload()
                }}
              />
            </div>
          ))}
        </div>
      </main>
    </>
  )
}

export function ProjectScreen() {
  const { universeId = '', projectId = '' } = useParams()
  const navigate = useNavigate()
  const { data, loading, error, reload } = useResource<VideoProject>(
    `/api/universes/${universeId}/video-projects/${projectId}`,
  )
  const action = useAction()
  const [jobId, setJobId] = useState<string | null>(null)
  const [planOpen, setPlanOpen] = useState(false)
  const [edicion, setEdicion] = useState<ResumenEdicion | null>(null)
  const base = `/api/universes/${universeId}/video-projects/${projectId}`

  const run = async (fn: () => Promise<{ id: string }>) => {
    const job = await action.run(fn)
    if (job) setJobId(job.id)
  }

  const scenes = data?.scenes ?? []
  const generated = scenes.filter((scene) => !scene.reuses_scene_id)
  const storyApproved = (data?.story as { status?: string })?.status === 'APPROVED'
  const storyboardApproved = data?.storyboard_status === 'APPROVED'

  return (
    <>
      <TopBar
        title={data?.title || 'Videoclip'}
        back
        action={data && <StatusBadge status={data.status} />}
      />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        {data && (
          <>
            {/* The production rail (PRD 38) */}
            <Card>
              <h3>Produccion</h3>
              <div className="rail">
                {(data.stage_summary ?? []).map((stage) => (
                  <div
                    key={stage.key}
                    className={`rail-step ${
                      stage.status === 'APPROVED'
                        ? 'done'
                        : stage.status === 'IN_PROGRESS'
                          ? 'active'
                          : ''
                    }`}
                  >
                    <span className="rail-dot">{stage.status === 'APPROVED' ? '✓' : ''}</span>
                    <span className="grow">
                      <span className="name">{stage.label}</span>
                      {stage.detail && <div className="muted">{stage.detail}</div>}
                    </span>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <h3>Historia</h3>
              <button
                className="btn block"
                disabled={action.busy}
                onClick={() =>
                  run(() =>
                    api.post(`${base}/concept`, { idempotency_key: newIdempotencyKey('vc') }),
                  )
                }
              >
                Pedir propuesta al Director
              </button>
              {data.concept && <p className="sub">{data.concept}</p>}
              {Object.entries(data.story ?? {})
                .filter(([key, value]) => key !== 'status' && value)
                .map(([key, value]) => (
                  <div key={key}>
                    <div className="muted">{key}</div>
                    <div>{String(value)}</div>
                  </div>
                ))}
              {data.wardrobe_notes && (
                <div>
                  <div className="muted">Vestuario de este video</div>
                  <div>{data.wardrobe_notes}</div>
                </div>
              )}
              {data.location_notes && (
                <div>
                  <div className="muted">Donde ocurre</div>
                  <div>{data.location_notes}</div>
                </div>
              )}
              <button
                className="btn ok block"
                disabled={action.busy || storyApproved}
                onClick={async () => {
                  await action.run(() => api.post(`${base}/story/approve`))
                  await reload()
                }}
              >
                {storyApproved ? 'Historia aprobada' : 'Aprobar historia'}
              </button>
            </Card>

            <Card>
              <h3>Storyboard</h3>
              <p className="muted" style={{ margin: 0 }}>
                Escenas de 8 segundos, cada una con dos o tres planos cortos dentro: el montaje
                corta cada 3 a 5 segundos, como un videoclip profesional. La musica suena desde el
                segundo 0 con el artista ya en pantalla. El Director busca primero que tomas puede
                reaprovechar —los coros que se repiten— antes de proponer generar nuevas, y el
                vestuario y los sitios van escritos dentro de cada escena.
              </p>
              <button
                className="btn block"
                disabled={action.busy || !storyApproved}
                onClick={() =>
                  run(() =>
                    api.post(`${base}/storyboard`, { idempotency_key: newIdempotencyKey('sb') }),
                  )
                }
              >
                Pedir storyboard
              </button>
              {data.storyboard_notes && <div className="notice">{data.storyboard_notes}</div>}
              <div className="row between muted">
                <span>{scenes.length} escenas</span>
                <span>{scenes.length - generated.length} reutilizadas</span>
              </div>
              <button
                className="btn ok block"
                disabled={action.busy || scenes.length === 0 || storyboardApproved}
                onClick={async () => {
                  await action.run(() => api.post(`${base}/storyboard/approve`))
                  await reload()
                }}
              >
                {storyboardApproved ? 'Storyboard aprobado' : 'Aprobar storyboard'}
              </button>
            </Card>

            <button className="btn block" onClick={() => setPlanOpen(true)}>
              Ver Production Plan y coste estimado
            </button>

            {scenes.length > 0 && (
              <>
                <div className="section-title">Escenas</div>
                <div className="list">
                  {scenes.map((scene) => (
                    <SceneRow
                      key={scene.id}
                      scene={scene}
                      onOpen={() => navigate(`/u/${universeId}/scenes/${scene.id}`)}
                    />
                  ))}
                </div>
              </>
            )}

            <Card>
              <h3>Ensamblaje</h3>
              <p className="muted" style={{ margin: 0 }}>
                El master usa siempre el audio aprobado. La version 9:16 se deriva del master por
                reencuadre y no cuesta nada generar. El Editor decide como se corta el videoclip
                a partir del storyboard y de la cancion.
              </p>
              <button
                className="btn primary block"
                disabled={action.busy}
                onClick={() =>
                  run(() =>
                    api.post(`${base}/assemble`, {
                      formats: ['16:9', '9:16'],
                      idempotency_key: newIdempotencyKey('asm'),
                    }),
                  )
                }
              >
                Ensamblar 16:9 y 9:16
              </button>
              {edicion && <Montaje edicion={edicion} />}
              {data.master_16x9_url && (
                <video className="media wide" controls preload="none" src={data.master_16x9_url} />
              )}
              {data.master_9x16_url && (
                <video className="media" controls preload="none" src={data.master_9x16_url} />
              )}
              {!data.master_16x9_url && data.edl_path && (
                <div className="notice">
                  El plan de montaje esta listo, pero el video todavia no se ha renderizado.
                  Vuelve a tocar Ensamblar para producir el MP4 final.
                </div>
              )}
            </Card>

            {jobId && (
              <JobWatcher
                universeId={universeId}
                jobId={jobId}
                onReady={(job) => {
                  setJobId(null)
                  const resumen = (job.result as { edit?: ResumenEdicion } | null)?.edit
                  if (resumen) setEdicion(resumen)
                  void reload()
                }}
              />
            )}
          </>
        )}
      </main>

      {planOpen && (
        <PlanSheet
          universeId={universeId}
          projectId={projectId}
          onClose={() => setPlanOpen(false)}
        />
      )}
    </>
  )
}

interface ResumenEdicion {
  notes: string
  hard_cuts: number
  transitions: number
  joins: { after_scene: number; type: string; seconds: number }[]
}

const NOMBRE_TRANSICION: Record<string, string> = {
  cut: 'corte seco',
  fade: 'fundido',
  fadeblack: 'a negro',
  dissolve: 'disolvencia',
}

/** Lo que decidio el Editor, para que se vea sin tener que preguntar. */
function Montaje({ edicion }: { edicion: ResumenEdicion }) {
  const blandas = edicion.joins.filter((j) => j.type !== 'cut')
  return (
    <div className="notice">
      <strong>Como lo ha montado el Editor</strong>
      {edicion.notes && <p style={{ margin: '6px 0' }}>{edicion.notes}</p>}
      <div>
        {edicion.hard_cuts} cortes secos
        {edicion.transitions > 0 ? ` y ${edicion.transitions} transiciones` : ', sin transiciones'}
        .
      </div>
      {blandas.map((join) => (
        <div key={join.after_scene} className="muted">
          Tras la escena {join.after_scene + 1}: {NOMBRE_TRANSICION[join.type] ?? join.type} de{' '}
          {join.seconds}s
        </div>
      ))}
    </div>
  )
}

function SceneRow({ scene, onOpen }: { scene: Scene; onOpen: () => void }) {
  return (
    <Card onClick={onOpen}>
      <div className="row between">
        <strong>Escena {scene.index + 1}</strong>
        {scene.reuses_scene_id ? (
          <span className="badge accent">Reutiliza</span>
        ) : (
          <span className="muted">{scene.duration_seconds}s</span>
        )}
      </div>
      <div className="sub">{scene.action || scene.reuse_note}</div>
      <div className="row wrap">
        <span className={`badge ${scene.image_status === 'APPROVED' ? 'approved' : 'draft'}`}>
          Imagen {scene.image_status === 'APPROVED' ? 'ok' : 'pendiente'}
        </span>
        <span className={`badge ${scene.clip_status === 'APPROVED' ? 'approved' : 'draft'}`}>
          Clip {scene.clip_status === 'APPROVED' ? 'ok' : 'pendiente'}
        </span>
      </div>
    </Card>
  )
}

function PlanSheet({
  universeId,
  projectId,
  onClose,
}: {
  universeId: string
  projectId: string
  onClose: () => void
}) {
  const [image, setImage] = useState<ModelChoice | null>(null)
  const [video, setVideo] = useState<ModelChoice | null>(null)
  const [plan, setPlan] = useState<ProductionPlan | null>(null)
  const action = useAction()

  const build = async () => {
    if (!image || !video) return
    const result = await action.run(() =>
      api.post<ProductionPlan>(
        `/api/universes/${universeId}/video-projects/${projectId}/plan`,
        {
          image_model: image.model,
          image_variant: image.variant,
          video_model: video.model,
          video_variant: video.variant,
          attempts_per_image: 2,
          attempts_per_clip: 1.5,
        },
      ),
    )
    if (result) setPlan(result)
  }

  return (
    <Sheet title="Production Plan" onClose={onClose}>
      <ModelPicker kind="image" value={image} onChange={setImage} label="Modelo de imagen" />
      <ModelPicker kind="video" value={video} onChange={setVideo} label="Modelo de video" />
      <ErrorNote error={action.error} onDismiss={action.clearError} />
      <button
        className="btn primary block"
        disabled={!image || !video || action.busy}
        onClick={build}
      >
        Calcular
      </button>
      {plan && <pre className="block">{plan.text}</pre>}
    </Sheet>
  )
}
