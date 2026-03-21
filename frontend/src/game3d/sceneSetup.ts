import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js'

export interface SceneContext {
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  renderer: THREE.WebGLRenderer
  labelRenderer: CSS2DRenderer
  controls: OrbitControls
  clock: THREE.Clock
  dispose: () => void
}

function createCheckerTexture(): THREE.CanvasTexture {
  const size = 512
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!

  const tileSize = 64
  const colorA = '#2d3048'
  const colorB = '#262940'

  for (let y = 0; y < size; y += tileSize) {
    for (let x = 0; x < size; x += tileSize) {
      const isEven = ((x / tileSize) + (y / tileSize)) % 2 === 0
      ctx.fillStyle = isEven ? colorA : colorB
      ctx.fillRect(x, y, tileSize, tileSize)
    }
  }

  // Subtle border lines
  ctx.strokeStyle = '#3a3d5a'
  ctx.lineWidth = 1
  for (let i = 0; i <= size; i += tileSize) {
    ctx.beginPath()
    ctx.moveTo(i, 0)
    ctx.lineTo(i, size)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(0, i)
    ctx.lineTo(size, i)
    ctx.stroke()
  }

  const texture = new THREE.CanvasTexture(canvas)
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(6, 6)
  return texture
}

export function createScene(canvas: HTMLCanvasElement, labelContainer: HTMLDivElement): SceneContext {
  // Scene
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x141628)
  scene.fog = new THREE.Fog(0x141628, 35, 60)

  // Camera
  const camera = new THREE.PerspectiveCamera(
    35,
    canvas.clientWidth / canvas.clientHeight,
    0.1,
    80
  )
  camera.position.set(20, 20, 20)
  camera.lookAt(0, 0, 0)

  // WebGL Renderer
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
  renderer.setSize(canvas.clientWidth, canvas.clientHeight)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1

  // CSS2D Renderer (for head labels)
  const labelRenderer = new CSS2DRenderer({ element: labelContainer })
  labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight)
  labelRenderer.domElement.style.position = 'absolute'
  labelRenderer.domElement.style.top = '0'
  labelRenderer.domElement.style.left = '0'
  labelRenderer.domElement.style.pointerEvents = 'none'

  // Controls
  const controls = new OrbitControls(camera, canvas)
  controls.target.set(0, 0.5, 0)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minPolarAngle = Math.PI * 0.1
  controls.maxPolarAngle = Math.PI * 0.45
  controls.minDistance = 6
  controls.maxDistance = 50
  controls.update()

  // Lights
  const ambient = new THREE.AmbientLight(0xfff5e6, 0.5)
  scene.add(ambient)

  const hemisphere = new THREE.HemisphereLight(0xc8e0ff, 0x8f7e6d, 0.35)
  scene.add(hemisphere)

  const sun = new THREE.DirectionalLight(0xffedc9, 1.6)
  sun.position.set(8, 12, 6)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  sun.shadow.camera.near = 0.5
  sun.shadow.camera.far = 60
  sun.shadow.camera.left = -24
  sun.shadow.camera.right = 24
  sun.shadow.camera.top = 24
  sun.shadow.camera.bottom = -24
  sun.shadow.bias = -0.0002
  scene.add(sun)

  const fill = new THREE.DirectionalLight(0xbfd8ff, 0.35)
  fill.position.set(-5, 6, -3)
  scene.add(fill)

  // === Modern office floor ===
  // Main floor (checker pattern)
  const floorTexture = createCheckerTexture()
  const floorGeo = new THREE.PlaneGeometry(48, 48)
  const floorMat = new THREE.MeshStandardMaterial({
    map: floorTexture,
    roughness: 0.75,
    metalness: 0.05,
  })
  const floor = new THREE.Mesh(floorGeo, floorMat)
  floor.rotation.x = -Math.PI / 2
  floor.receiveShadow = true
  scene.add(floor)

  // Raised platform for desk area (subtle)
  const platformGeo = new THREE.BoxGeometry(20, 0.06, 12)
  const platformMat = new THREE.MeshStandardMaterial({
    color: 0x343756,
    roughness: 0.6,
    metalness: 0.1,
  })
  const platform = new THREE.Mesh(platformGeo, platformMat)
  platform.position.set(0, 0.03, 0)
  platform.receiveShadow = true
  scene.add(platform)

  // Edge trim on platform
  const trimGeo = new THREE.BoxGeometry(20.1, 0.02, 12.1)
  const trimMat = new THREE.MeshStandardMaterial({
    color: 0x10b981,
    roughness: 0.3,
    metalness: 0.4,
    emissive: 0x10b981,
    emissiveIntensity: 0.15,
  })
  const trim = new THREE.Mesh(trimGeo, trimMat)
  trim.position.set(0, 0.065, 0)
  scene.add(trim)

  const clock = new THREE.Clock()

  // Resize handler
  const onResize = () => {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h)
    labelRenderer.setSize(w, h)
  }
  const resizeObserver = new ResizeObserver(onResize)
  resizeObserver.observe(canvas)

  const dispose = () => {
    resizeObserver.disconnect()
    controls.dispose()
    renderer.dispose()
    floorGeo.dispose()
    floorMat.dispose()
    floorTexture.dispose()
    platformGeo.dispose()
    platformMat.dispose()
    trimGeo.dispose()
    trimMat.dispose()
  }

  return { scene, camera, renderer, labelRenderer, controls, clock, dispose }
}
