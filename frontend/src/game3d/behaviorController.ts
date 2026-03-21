import * as THREE from 'three'
import type { ActorManager } from './actorManager'
import type { DeskPosition3D } from './types'

const ROAM_SPEED = 0.6
const ROAM_PAUSE_MIN = 3
const ROAM_PAUSE_MAX = 8
const REACH_THRESHOLD = 0.2
const MIN_ACTOR_DISTANCE = 1.0

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
    actor.roamTimer = Math.random() * 2
    actorManager.updateLabel(actor)
    pickRoamTarget(actor)
  }

  function pickRoamTarget(actor: { memberId: number; model: THREE.Group; targetPosition: THREE.Vector3 | null }) {
    // Try a few times to find a spot away from other actors
    for (let attempt = 0; attempt < 8; attempt++) {
      const x = bounds.minX + Math.random() * (bounds.maxX - bounds.minX)
      const z = bounds.minZ + Math.random() * (bounds.maxZ - bounds.minZ)
      const candidate = new THREE.Vector3(x, 0, z)

      let tooClose = false
      for (const other of actorManager.actors.values()) {
        if (other.memberId === actor.memberId) continue
        if (other.model.position.distanceTo(candidate) < MIN_ACTOR_DISTANCE) {
          tooClose = true
          break
        }
      }
      if (!tooClose) {
        actor.targetPosition = candidate
        return
      }
    }
    // Fallback: just pick any spot
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

    // Push apart actors that are too close
    const allActors = [...actorManager.actors.values()]
    for (let i = 0; i < allActors.length; i++) {
      for (let j = i + 1; j < allActors.length; j++) {
        const a = allActors[i]!
        const b = allActors[j]!
        const dist = a.model.position.distanceTo(b.model.position)
        if (dist < MIN_ACTOR_DISTANCE && dist > 0.01) {
          const push = new THREE.Vector3()
            .subVectors(a.model.position, b.model.position)
            .normalize()
            .multiplyScalar((MIN_ACTOR_DISTANCE - dist) * 0.5 * delta * 3)
          a.model.position.add(push)
          b.model.position.sub(push)
        }
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

    // Smooth face direction of movement
    const targetAngle = Math.atan2(dir.x, dir.z)
    const currentAngle = actor.model.rotation.y
    let diff = targetAngle - currentAngle
    while (diff > Math.PI) diff -= Math.PI * 2
    while (diff < -Math.PI) diff += Math.PI * 2
    actor.model.rotation.y += diff * Math.min(1, delta * 6)
  }

  function releaseDesk(deskIndex: number) {
    if (desks[deskIndex]) {
      desks[deskIndex].occupied = false
    }
  }

  return { assignBusy, assignIdle, releaseDesk, update }
}

export type BehaviorController = ReturnType<typeof createBehaviorController>
