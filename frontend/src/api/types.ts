export type CanonStatus = 'DRAFT' | 'APPROVED' | 'REJECTED' | 'ARCHIVED'

export type JobState =
  | 'QUEUED'
  | 'PROCESSING'
  | 'READY'
  | 'APPROVED'
  | 'REJECTED'
  | 'FAILED'
  | 'CANCELLED'

export interface Variant {
  key: string
  label: string
  unit: string
  price?: number
  price_input?: number
  price_output?: number
}

export interface ModelSpec {
  id: string
  kind: 'text' | 'image' | 'music' | 'video' | 'speech'
  label: string
  status: string
  role_hint: string
  default_variant: string | null
  variants: Variant[]
  capabilities: Record<string, unknown>
}

export interface Registry {
  currency: string
  models: ModelSpec[]
  excluded: { id: string; kind: string; reason: string }[]
}

export interface Universe {
  id: string
  name: string
  tagline: string
  status: CanonStatus
  updated_at: string
}

export interface Job {
  id: string
  universe_id: string
  kind: string
  state: JobState
  model: string
  variant: string
  target_type: string
  target_id: string
  error: string | null
  attempts: number
  estimated_cost_usd: number
  actual_cost_usd: number
  created_at: string
  finished_at: string | null
  result: Record<string, unknown> | null
}

export interface PendingApproval {
  job_id: string
  universe_id: string
  universe_name: string
  kind: string
  target_type: string
  target_id: string
  model: string
  cost_usd: number
  finished_at: string | null
}

/** Un artista tal y como lo enseña la pantalla de inicio: con su cara, su
 *  género y cuántos videoclips tiene a medias. */
export interface UniverseCard extends Universe {
  cover_path: string
  artist_name: string
  projects_active: number
  projects_total: number
}

export interface RecentProject {
  id: string
  universe_id: string
  universe_name: string
  title: string
  status: string
  stage: string
  cover_path: string
  updated_at: string
}

export interface Home {
  universes: UniverseCard[]
  active_jobs: (Job & { universe_name: string })[]
  pending_approvals: PendingApproval[]
  recent_projects: RecentProject[]
}

export interface VoiceProfile {
  lines: string[]
  speaking_voice_secret: string | null
}

export interface ArtistBible {
  id: string
  universe_id: string
  status: CanonStatus
  version: number
  identity: Record<string, unknown>
  musical: Record<string, unknown>
  visual: Record<string, unknown>
  communication: Record<string, unknown>
  preferences: {
    preferred_image_model: string | null
    preferred_image_variant: string | null
    preferred_video_model: string | null
    preferred_video_variant: string | null
    working_resolution: string
  }
  voice_profile: VoiceProfile
  summary?: string
}

export interface MasterShot {
  key: string
  label: string
  storage_path: string | null
  status: CanonStatus
  prompt?: string
}

export interface Character {
  id: string
  name: string
  role: string
  gender: string
  rasgos?: Record<string, string>
  apparent_age: string
  appearance: string
  personality: string
  master_shots: MasterShot[]
  reference_image_paths: string[]
  status: CanonStatus
}

export interface Outfit {
  id: string
  name: string
  category: string
  description: string
  image_path: string | null
  status: CanonStatus
}

export interface Location {
  id: string
  name: string
  description: string
  lighting: string
  time_of_day: string
  reference_paths: string[]
  status: CanonStatus
}

export interface SongVersion {
  version: number
  audio_path: string | null
  url?: string | null
  duration_seconds: number
  model: string
  status: CanonStatus
  created_at: string
}

export interface Song {
  id: string
  title: string
  concept: Record<string, unknown> & { status?: CanonStatus }
  lyrics: string
  lyrics_author: string
  lyrics_status: CanonStatus
  music_prompt: string
  genre: string
  bpm: number | null
  mood: string
  structure: string[]
  requested_duration_seconds: number
  versions: SongVersion[]
  approved_version: number | null
  approved_master_path: string | null
  cover_path: string | null
  video_project_id: string | null
  status: CanonStatus
  cost_usd: number
}

export interface Scene {
  id: string
  project_id: string
  index: number
  duration_seconds: number
  song_timestamp: string
  action: string
  emotion: string
  camera: string
  lighting: string
  environment: string
  dialogue: string
  image_prompt?: string
  video_prompt?: string
  reuses_scene_id: string | null
  reuse_note: string
  reuse_forced_by_user: boolean
  image_id: string | null
  image_status: CanonStatus
  clip_id: string | null
  clip_status: CanonStatus
  status: CanonStatus
  cost_usd: number
}

export interface StageSummary {
  key: string
  label: string
  status: string
  detail: string
  cost_usd?: number
}

export interface VideoProject {
  id: string
  song_id: string
  title: string
  video_type: string
  concept: string
  story: Record<string, unknown> & { status?: CanonStatus }
  character_ids: string[]
  location_ids: string[]
  wardrobe_ids: string[]
  storyboard_status: CanonStatus
  storyboard_notes?: string
  production_plan: ProductionPlan | null
  master_16x9_path: string | null
  master_9x16_path: string | null
  master_16x9_url?: string | null
  master_9x16_url?: string | null
  edl_path?: string | null
  status: CanonStatus
  scenes?: Scene[]
  stage_summary?: StageSummary[]
}

export interface ProductionPlan {
  project_title: string
  video_type: string
  scenes: number
  characters: number
  locations: number
  wardrobe: number
  scene_images: { count: number; model: string; variant: string; cost_usd: number }
  video_clips: {
    count: number
    model: string
    variant: string
    seconds_each: number
    audio: boolean
    cost_usd: number
  }
  reused_takes: number
  vertical_derivatives: number
  estimated_generation_cost_usd: number
  text?: string
}

export interface ContentPiece {
  id: string
  kind: string
  bts_kind: string | null
  title: string
  script: string
  spoken_text?: string
  spoken_audio_path: string | null
  storage_path: string | null
  url: string | null
  voice_url: string | null
  status: CanonStatus
}

export interface ExportPackage {
  id: string
  song_id: string
  root_path: string
  files: { folder: string; name: string; package_path: string; url: string }[]
  archive_path: string | null
  archive_url: string | null
  tree?: string
}

export interface ApiError {
  code: string
  message: string
  details: Record<string, unknown>
}
