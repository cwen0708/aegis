import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js'
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js'
import type { Actor3D, MemberState } from './types'
import { CHARACTER_MODELS } from './types'

const CROSS_FADE_DURATION = 0.25
const loader = new GLTFLoader()

// Cache loaded GLTF results so each model URL is fetched only once
const gltfCache = new Map<string, { scene: THREE.Group; animations: THREE.AnimationClip[] }>()

async function loadGLTF(url: string) {
  const cached = gltfCache.get(url)
  if (cached) return cached
  const gltf = await loader.loadAsync(url)
  const result = { scene: gltf.scene, animations: gltf.animations }
  gltfCache.set(url, result)
  return result
}

export function createActorManager(scene: THREE.Scene) {
  const actors = new Map<number, Actor3D>()

  function getModelUrl(memberId: number): string {
    return CHARACTER_MODELS[memberId % CHARACTER_MODELS.length]!
  }

  function createLabel(name: string, state: MemberState): { div: HTMLDivElement; obj: CSS2DObject } {
    const div = document.createElement('div')
    div.className = 'head-label-3d'
    div.innerHTML = `
      <div class="hl-name">${name}</div>
      <div class="hl-state ${state}">${state === 'busy' ? '⚡ working' : '💤 idle'}</div>
    `
    const obj = new CSS2DObject(div)
    obj.position.set(0, 1.8, 0)
    return { div, obj }
  }

  function updateLabel(actor: Actor3D) {
    const stateEl = actor.labelDiv.querySelector('.hl-state')
    if (stateEl) {
      stateEl.className = `hl-state ${actor.state}`
      stateEl.textContent = actor.state === 'busy' ? '⚡ working' : '💤 idle'
    }
  }

  function playAction(actor: Actor3D, actionName: string) {
    if (actor.currentAction === actionName) return
    const prev = actor.actions.get(actor.currentAction)
    const next = actor.actions.get(actionName)
    if (!next) return
    if (prev) {
      prev.fadeOut(CROSS_FADE_DURATION)
    }
    next.reset().fadeIn(CROSS_FADE_DURATION).play()
    actor.currentAction = actionName
  }

  async function addActor(
    memberId: number,
    name: string,
    provider: string,
    position: THREE.Vector3,
    state: MemberState = 'idle'
  ): Promise<Actor3D> {
    // Remove existing actor with same ID
    removeActor(memberId)

    const url = getModelUrl(memberId)
    const { scene: origScene, animations } = await loadGLTF(url)

    // Clone with SkeletonUtils to properly handle SkinnedMesh + bones
    const model = SkeletonUtils.clone(origScene) as THREE.Group
    model.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh
        mesh.castShadow = true
        mesh.receiveShadow = false
      }
    })

    model.position.copy(position)
    scene.add(model)

    const mixer = new THREE.AnimationMixer(model)
    const actions = new Map<string, THREE.AnimationAction>()

    // Clone each clip so each actor has independent animation state
    for (const clip of animations) {
      const action = mixer.clipAction(clip.clone())
      // Normalize common clip names: e.g. "Idle", "Walk_A", "Sitting", etc.
      const normalizedName = normalizeClipName(clip.name)
      actions.set(normalizedName, action)
    }

    // If no animations in GLB, create a simple bob animation as fallback
    if (actions.size === 0) {
      const bobTrack = new THREE.NumberKeyframeTrack(
        '.position[y]',
        [0, 0.5, 1],
        [position.y, position.y + 0.05, position.y]
      )
      const bobClip = new THREE.AnimationClip('idle', 1, [bobTrack])
      actions.set('idle', mixer.clipAction(bobClip))
    }

    // Label
    const { div: labelDiv, obj: labelObj } = createLabel(name, state)
    model.add(labelObj)

    const actor: Actor3D = {
      memberId,
      name,
      provider,
      state,
      model,
      mixer,
      actions,
      currentAction: '',
      targetPosition: null,
      roamTimer: 0,
      labelDiv,
    }

    // Start with idle
    const startAnim = state === 'busy' ? 'sit' : 'idle'
    const startAction = actions.get(startAnim) || actions.values().next().value
    if (startAction) {
      startAction.play()
      actor.currentAction = startAnim
    }

    actors.set(memberId, actor)
    return actor
  }

  function removeActor(memberId: number) {
    const actor = actors.get(memberId)
    if (!actor) return
    actor.mixer.stopAllAction()
    scene.remove(actor.model)
    actor.model.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh
        mesh.geometry.dispose()
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        mats.forEach(m => m.dispose())
      }
    })
    actor.labelDiv.remove()
    actors.delete(memberId)
  }

  function update(delta: number) {
    for (const actor of actors.values()) {
      actor.mixer.update(delta)
    }
  }

  function dispose() {
    for (const id of [...actors.keys()]) {
      removeActor(id)
    }
    gltfCache.clear()
  }

  return {
    actors,
    addActor,
    removeActor,
    playAction,
    updateLabel,
    update,
    dispose,
  }
}

/** Normalize KayKit animation clip names to simple keys */
function normalizeClipName(name: string): string {
  const lower = name.toLowerCase()
  if (lower.includes('idle')) return 'idle'
  if (lower.includes('walk')) return 'walk'
  if (lower.includes('run')) return 'run'
  if (lower.includes('sit')) return 'sit'
  if (lower.includes('typ')) return 'typing'
  if (lower.includes('wave')) return 'wave'
  if (lower.includes('jump')) return 'jump'
  if (lower.includes('attack')) return 'attack'
  if (lower.includes('interact')) return 'interact'
  // Keep original name as fallback
  return lower.replace(/\s+/g, '_')
}

export type ActorManager = ReturnType<typeof createActorManager>
