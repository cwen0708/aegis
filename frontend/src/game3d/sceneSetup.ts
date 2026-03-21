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

export function createScene(canvas: HTMLCanvasElement, labelContainer: HTMLDivElement): SceneContext {
  // Scene
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x1a1a2e)
  scene.fog = new THREE.Fog(0x1a1a2e, 30, 55)

  // Camera
  const camera = new THREE.PerspectiveCamera(
    35,
    canvas.clientWidth / canvas.clientHeight,
    0.1,
    50
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
  const ambient = new THREE.AmbientLight(0xfff5e6, 0.4)
  scene.add(ambient)

  const hemisphere = new THREE.HemisphereLight(0xc8e0ff, 0x8f7e6d, 0.3)
  scene.add(hemisphere)

  const sun = new THREE.DirectionalLight(0xffedc9, 1.8)
  sun.position.set(5, 8, 4)
  sun.castShadow = true
  sun.shadow.mapSize.set(1024, 1024)
  sun.shadow.camera.near = 0.5
  sun.shadow.camera.far = 60
  sun.shadow.camera.left = -24
  sun.shadow.camera.right = 24
  sun.shadow.camera.top = 24
  sun.shadow.camera.bottom = -24
  sun.shadow.bias = -0.0003
  scene.add(sun)

  const fill = new THREE.DirectionalLight(0xbfd8ff, 0.4)
  fill.position.set(-3, 4, -2)
  scene.add(fill)

  // Ground plane
  const groundGeo = new THREE.PlaneGeometry(48, 48)
  const groundMat = new THREE.MeshStandardMaterial({
    color: 0x2a2a4a,
    roughness: 0.9,
    metalness: 0.05,
  })
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.receiveShadow = true
  scene.add(ground)

  // Grid helper (subtle)
  const grid = new THREE.GridHelper(48, 48, 0x3a3a5a, 0x3a3a5a)
  grid.position.y = 0.005
  ;(grid.material as THREE.Material).opacity = 0.3
  ;(grid.material as THREE.Material).transparent = true
  scene.add(grid)

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
    groundGeo.dispose()
    groundMat.dispose()
  }

  return { scene, camera, renderer, labelRenderer, controls, clock, dispose }
}
