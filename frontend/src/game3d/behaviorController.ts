import * as THREE from 'three'
import type { ActorManager } from './actorManager'
import type { DeskPosition3D } from './types'

const ROAM_SPEED = 0.8
const ROAM_PAUSE_MIN = 2
const ROAM_PAUSE_MAX = 6
const REACH_THRESHOLD = 0.15

export function createBehaviorController(
  actorManager: ActorManager,
  desks: DeskPosition3D[],
  bounds: { minX: number; maxX: number; minZ: number; maxZ: number }
) {
  function assignBusy(memberId: number, deskIndex: number) {
    const actor = actorManager.actors.get(memberId)
    if (!actor) return
    const desk = desks[deskIndex]
    if (!desk) return

    actor.state = 'busy'
    actor.targetPosition = desk.position.clone()
    desk.occupied = true
    actorManager.updateLabel(actor)
  }

  function assignIdle(memberId: number) {
    const actor = actorManager.actors.get(memberId)
    if (!actor) return
    actor.state = 'idle'
    actor.roamTimer = 0
    actorManager.updateLabel(actor)
    pickRoamTarget(actor)
  }

  function pickRoamTarget(actor: typeof actorManager.actors extends Map<number, infer V> ? V : never) {
    const x = bounds.minX + Math.random() * (bounds.maxX - bounds.minX)
    const z = bounds.minZ + Math.random() * (bounds.maxZ - bounds.minZ)
    actor.targetPosition = new THREE.Vector3(x, 0, z)
  }

  function update(delta: number) {
    for (const actor of actorManager.actors.values()) {
      if (actor.state === 'busy') {
        updateBusy(actor, delta)
      } else {
        updateIdle(actor, delta)
      }
    }
  }

  function updateBusy(actor: ReturnType<typeof actorManager.actors.get> & object, delta: number) {
    if (!actor.targetPosition) {
      actorManager.playAction(actor, 'sit')
      return
    }

    const dist = actor.model.position.distanceTo(actor.targetPosition)
    if (dist < REACH_THRESHOLD) {
      actor.model.position.copy(actor.targetPosition)
      actor.targetPosition = null
      actorManager.playAction(actor, 'sit')
      return
    }

    // Move toward desk
    moveToward(actor, delta, ROAM_SPEED * 1.2)
    actorManager.playAction(actor, 'walk')
  }

  function updateIdle(actor: ReturnType<typeof actorManager.actors.get> & object, delta: number) {
    if (!actor.targetPosition) {
      actor.roamTimer -= delta
      if (actor.roamTimer <= 0) {
        pickRoamTarget(actor)
        actorManager.playAction(actor, 'walk')
      } else {
        actorManager.playAction(actor, 'idle')
      }
      return
    }

    const dist = actor.model.position.distanceTo(actor.targetPosition)
    if (dist < REACH_THRESHOLD) {
      actor.model.position.copy(actor.targetPosition)
      actor.targetPosition = null
      actor.roamTimer = ROAM_PAUSE_MIN + Math.random() * (ROAM_PAUSE_MAX - ROAM_PAUSE_MIN)
      actorManager.playAction(actor, 'idle')
      return
    }

    moveToward(actor, delta, ROAM_SPEED)
    actorManager.playAction(actor, 'walk')
  }

  function moveToward(actor: { model: THREE.Group; targetPosition: THREE.Vector3 | null }, delta: number, speed: number) {
    if (!actor.targetPosition) return
    const dir = new THREE.Vector3()
      .subVectors(actor.targetPosition, actor.model.position)
      .normalize()

    actor.model.position.addScaledVector(dir, speed * delta)

    // Face direction of movement
    const angle = Math.atan2(dir.x, dir.z)
    actor.model.rotation.y = angle
  }

  function releaseDesk(deskIndex: number) {
    if (desks[deskIndex]) {
      desks[deskIndex].occupied = false
    }
  }

  return { assignBusy, assignIdle, releaseDesk, update }
}

export type BehaviorController = ReturnType<typeof createBehaviorController>
