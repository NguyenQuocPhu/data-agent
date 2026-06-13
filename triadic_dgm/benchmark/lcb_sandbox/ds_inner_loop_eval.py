from collections import Counter, defaultdict

def can_chain(domino_pairs):
    if not domino_pairs:
        return True

    vertex_degree_counts = Counter()
    adjacency_map = defaultdict(list)

    for u, v in domino_pairs:
        vertex_degree_counts[u] += 1
        vertex_degree_counts[v] += 1
        adjacency_map[u].append(v)
        adjacency_map[v].append(u)

    unique_pip_values = set(vertex_degree_counts.keys())

    start_node = next(iter(unique_pip_values))
    visited = set()
    stack = [start_node]

    while stack:
        node = stack.pop()
        if node not in visited:
            visited.add(node)
            for neighbor in adjacency_map[node]:
                if neighbor not in visited:
                    stack.append(neighbor)

    graph_connectivity_status = len(visited) == len(unique_pip_values)

    odd_degree_vertex_count = sum(1 for count in vertex_degree_counts.values() if count % 2 != 0)

    return graph_connectivity_status and (odd_degree_vertex_count == 0 or odd_degree_vertex_count == 2)
