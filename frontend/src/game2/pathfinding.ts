interface Node {
  col: number
  row: number
  g: number  // cost from start
  h: number  // heuristic to goal
  f: number  // g + h
  parent: Node | null
}

function heuristic(a: { col: number; row: number }, b: { col: number; row: number }): number {
  // Manhattan distance
  return Math.abs(a.col - b.col) + Math.abs(a.row - b.row)
}

function nodeKey(col: number, row: number): string {
  return `${col},${row}`
}

/**
 * A* pathfinding algorithm
 * Returns array of {col, row} from start to end (excluding start, including end)
 * Returns empty array if no path found
 */
export function findPath(
  startCol: number,
  startRow: number,
  endCol: number,
  endRow: number,
  walkableTiles: Array<{ col: number; row: number }>
): Array<{ col: number; row: number }> {
  // Build walkable set for O(1) lookup
  const walkableSet = new Set<string>()
  for (const t of walkableTiles) {
    walkableSet.add(nodeKey(t.col, t.row))
  }

  // Round to integers
  const start = { col: Math.round(startCol), row: Math.round(startRow) }
  const end = { col: Math.round(endCol), row: Math.round(endRow) }

  // Check if end is walkable
  if (!walkableSet.has(nodeKey(end.col, end.row))) {
    return []
  }

  const openList: Node[] = []
  const closedSet = new Set<string>()

  const startNode: Node = {
    col: start.col,
    row: start.row,
    g: 0,
    h: heuristic(start, end),
    f: 0,
    parent: null,
  }
  startNode.f = startNode.g + startNode.h
  openList.push(startNode)

  // 4-directional movement
  const directions = [
    { dc: 0, dr: -1 }, // up
    { dc: 1, dr: 0 },  // right
    { dc: 0, dr: 1 },  // down
    { dc: -1, dr: 0 }, // left
  ]

  let iterations = 0
  const maxIterations = 1000

  while (openList.length > 0 && iterations < maxIterations) {
    iterations++

    // Find node with lowest f
    openList.sort((a, b) => a.f - b.f)
    const current = openList.shift()!

    // Reached goal?
    if (current.col === end.col && current.row === end.row) {
      // Reconstruct path
      const path: Array<{ col: number; row: number }> = []
      let node: Node | null = current
      while (node && node.parent) {
        path.unshift({ col: node.col, row: node.row })
        node = node.parent
      }
      return path
    }

    closedSet.add(nodeKey(current.col, current.row))

    // Check neighbors
    for (const dir of directions) {
      const nc = current.col + dir.dc
      const nr = current.row + dir.dr
      const key = nodeKey(nc, nr)

      if (closedSet.has(key)) continue
      if (!walkableSet.has(key)) continue

      const g = current.g + 1
      const h = heuristic({ col: nc, row: nr }, end)
      const f = g + h

      // Check if already in open list with better g
      const existing = openList.find(n => n.col === nc && n.row === nr)
      if (existing) {
        if (g < existing.g) {
          existing.g = g
          existing.f = f
          existing.parent = current
        }
        continue
      }

      openList.push({
        col: nc,
        row: nr,
        g,
        h,
        f,
        parent: current,
      })
    }
  }

  // No path found
  return []
}

/**
 * Simplify path by removing intermediate points on straight lines
 */
export function simplifyPath(
  path: Array<{ col: number; row: number }>
): Array<{ col: number; row: number }> {
  if (path.length <= 2) return path

  const result: Array<{ col: number; row: number }> = [path[0]!]

  for (let i = 1; i < path.length - 1; i++) {
    const prev = path[i - 1]!
    const curr = path[i]!
    const next = path[i + 1]!

    // Check if direction changes
    const d1c = curr.col - prev.col
    const d1r = curr.row - prev.row
    const d2c = next.col - curr.col
    const d2r = next.row - curr.row

    if (d1c !== d2c || d1r !== d2r) {
      result.push(curr)
    }
  }

  result.push(path[path.length - 1]!)
  return result
}
