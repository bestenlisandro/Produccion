"""Shared explicit-precedence cycle validation, extracted without behavior changes."""

def has_cycle(edges) -> bool:
    graph: dict[object, set[object]] = {}
    for start, end in edges:
        graph.setdefault(start, set()).add(end)
        graph.setdefault(end, set())
    visiting: set[object] = set()
    visited: set[object] = set()

    def visit(node: object) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)
