"""Small native renderer for a safe Mermaid flowchart subset."""

from __future__ import absolute_import

import html
import math
import re
from collections import OrderedDict, deque

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo


class MermaidParseError(ValueError):
    pass


class MermaidNode(object):
    def __init__(self, node_id, label=None, shape="rect"):
        self.node_id = node_id
        self.label = label if label is not None else node_id
        self.shape = shape
        self.class_name = None
        self.style = {}
        self.width = 0
        self.height = 0
        self.x = 0
        self.y = 0
        self.level = 0


class MermaidEdge(object):
    def __init__(self, source, target, label="", dotted=False):
        self.source = source
        self.target = target
        self.label = label or ""
        self.dotted = bool(dotted)


class MermaidGraph(object):
    def __init__(self, direction):
        self.direction = direction
        self.nodes = OrderedDict()
        self.edges = []
        self.class_defs = {}

    def node(self, node_id, label=None, shape=None):
        item = self.nodes.get(node_id)
        if item is None:
            item = MermaidNode(node_id, label=label, shape=shape or "rect")
            self.nodes[node_id] = item
        else:
            if label is not None:
                item.label = label
            if shape is not None:
                item.shape = shape
        return item


_HEADER_RE = re.compile(r"^\s*(?:flowchart|graph)\s+(TD|TB|BT|LR|RL)\s*$", re.I)
_EDGE_RE = re.compile(r"^(.*?)\s*(-\.->|-->)\s*(?:\|([^|]*)\|\s*)?(.*?)\s*$")
_CLASSDEF_RE = re.compile(r"^\s*classDef\s+([A-Za-z_][\w-]*)\s+(.+?)\s*$")
_CLASS_RE = re.compile(r"^\s*class\s+([^\s]+)\s+([A-Za-z_][\w-]*)\s*$")
_NODE_ID = r"[A-Za-z_][A-Za-z0-9_-]*"
_NODE_PATTERNS = (
    (re.compile(r"^({})\(\[(.*)\]\)$".format(_NODE_ID), re.S), "stadium"),
    (re.compile(r"^({})\(\((.*)\)\)$".format(_NODE_ID), re.S), "circle"),
    (re.compile(r"^({})\{{(.*)\}}$".format(_NODE_ID), re.S), "diamond"),
    (re.compile(r"^({})\[(.*)\]$".format(_NODE_ID), re.S), "rect"),
    (re.compile(r"^({})\((.*)\)$".format(_NODE_ID), re.S), "rounded"),
    (re.compile(r"^({})$".format(_NODE_ID)), None),
)


def _clean_label(value):
    value = re.sub(r"(?i)<br\s*/?>", "\n", value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def _parse_node(expression):
    expression = expression.strip()
    for pattern, shape in _NODE_PATTERNS:
        match = pattern.match(expression)
        if not match:
            continue
        node_id = match.group(1)
        label = _clean_label(match.group(2)) if match.lastindex and match.lastindex > 1 else None
        return node_id, label, shape
    raise MermaidParseError("unsupported Mermaid node: {}".format(expression))


def _parse_style(value):
    result = {}
    for item in value.split(","):
        if ":" not in item:
            continue
        key, raw = item.split(":", 1)
        key = key.strip().lower()
        raw = raw.strip()
        if key in ("fill", "stroke", "stroke-width") and raw:
            result[key] = raw
    return result


def parse_mermaid_flowchart(source):
    """Parse a non-executable Mermaid flowchart subset into a graph model."""
    source = source or ""
    if len(source) > 200000:
        raise MermaidParseError("Mermaid block is too large")
    lines = source.splitlines()
    if not lines:
        raise MermaidParseError("empty Mermaid block")
    header_index = None
    graph = None
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("%%"):
            continue
        match = _HEADER_RE.match(line)
        if not match:
            raise MermaidParseError("only Mermaid flowchart/graph diagrams are supported")
        graph = MermaidGraph(match.group(1).upper())
        header_index = index
        break
    if graph is None:
        raise MermaidParseError("Mermaid flowchart header is missing")

    pending_classes = []
    for line in lines[header_index + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        match = _CLASSDEF_RE.match(line)
        if match:
            graph.class_defs[match.group(1)] = _parse_style(match.group(2))
            continue
        match = _CLASS_RE.match(line)
        if match:
            pending_classes.append((match.group(1).split(","), match.group(2)))
            continue
        match = _EDGE_RE.match(stripped)
        if match:
            source_expr, connector, edge_label, target_expr = match.groups()
            source_id, source_label, source_shape = _parse_node(source_expr)
            target_id, target_label, target_shape = _parse_node(target_expr)
            graph.node(source_id, source_label, source_shape)
            graph.node(target_id, target_label, target_shape)
            graph.edges.append(MermaidEdge(
                source_id, target_id, _clean_label(edge_label), connector == "-.->"))
            if len(graph.nodes) > 256 or len(graph.edges) > 512:
                raise MermaidParseError("Mermaid flowchart is too large")
            continue
        node_id, label, shape = _parse_node(stripped)
        graph.node(node_id, label, shape)
        if len(graph.nodes) > 256:
            raise MermaidParseError("Mermaid flowchart has too many nodes")

    for ids, class_name in pending_classes:
        for node_id in ids:
            node = graph.nodes.get(node_id)
            if node is None:
                raise MermaidParseError("class references unknown node: {}".format(node_id))
            node.class_name = class_name
            node.style = dict(graph.class_defs.get(class_name, {}))
    if not graph.nodes:
        raise MermaidParseError("Mermaid flowchart has no nodes")
    return graph


def _rgba(value, fallback):
    if not value:
        return fallback
    color = Gdk.RGBA()
    try:
        if color.parse(value):
            return color
    except Exception:
        pass
    return fallback


def _set_rgba(cr, color, alpha=None):
    cr.set_source_rgba(
        color.red, color.green, color.blue,
        color.alpha if alpha is None else alpha)


def _contrast_color(background, fallback):
    luminance = (0.2126 * background.red + 0.7152 * background.green +
                 0.0722 * background.blue)
    if luminance >= 0.62:
        return Gdk.RGBA(0.08, 0.08, 0.08, 1.0)
    if luminance <= 0.28:
        return Gdk.RGBA(0.96, 0.96, 0.96, 1.0)
    return fallback


def _rounded_rectangle(cr, x, y, width, height, radius):
    radius = min(radius, width / 2.0, height / 2.0)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2.0, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2.0)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2.0, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3.0 * math.pi / 2.0)
    cr.close_path()


class MermaidDiagram(Gtk.DrawingArea):
    """Theme-aware, non-executable native view for Mermaid flowcharts."""

    H_GAP = 56
    V_GAP = 72
    MARGIN = 28

    def __init__(self, source):
        Gtk.DrawingArea.__init__(self)
        self.source = source or ""
        self.graph = parse_mermaid_flowchart(self.source)
        self.get_style_context().add_class("minios-mermaid-diagram")
        accessible = self.get_accessible()
        if accessible is not None:
            accessible.set_name("Mermaid flowchart")
            accessible.set_description(self._accessible_description())
        self._layout_graph()
        self.connect("draw", self._on_draw)

    def _accessible_description(self):
        lines = []
        for edge in self.graph.edges:
            label = " ({})".format(edge.label) if edge.label else ""
            lines.append("{} -> {}{}".format(
                self.graph.nodes[edge.source].label.replace("\n", " "),
                self.graph.nodes[edge.target].label.replace("\n", " "), label))
        return "; ".join(lines)[:4000]

    @staticmethod
    def _measure_node(node):
        lines = node.label.splitlines() or [node.node_id]
        longest = max(len(line) for line in lines)
        width = max(120, min(300, 42 + longest * 7))
        height = max(48, 24 + len(lines) * 18)
        if node.shape == "diamond":
            width = min(320, width + 36)
            height += 24
        elif node.shape == "circle":
            size = max(width, height, 88)
            width = height = min(220, size)
        node.width = width
        node.height = height

    def _levels(self):
        adjacency = {node_id: [] for node_id in self.graph.nodes}
        indegree = {node_id: 0 for node_id in self.graph.nodes}
        for edge in self.graph.edges:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1
        roots = [node_id for node_id in self.graph.nodes if indegree[node_id] == 0]
        if not roots:
            roots = [next(iter(self.graph.nodes))]
        levels = {}
        queue = deque((node_id, 0) for node_id in roots)
        while queue:
            node_id, level = queue.popleft()
            previous = levels.get(node_id)
            if previous is not None and previous <= level:
                continue
            levels[node_id] = level
            for target in adjacency[node_id]:
                queue.append((target, level + 1))
        last = max(levels.values()) if levels else 0
        for node_id in self.graph.nodes:
            if node_id not in levels:
                last += 1
                levels[node_id] = last
        return levels

    def _layout_graph(self):
        levels = self._levels()
        by_level = OrderedDict()
        for node_id, node in self.graph.nodes.items():
            self._measure_node(node)
            node.level = levels[node_id]
            by_level.setdefault(node.level, []).append(node)
        vertical = self.graph.direction in ("TD", "TB", "BT")
        if vertical:
            canvas_width = 0
            rows = []
            for level in sorted(by_level):
                nodes = by_level[level]
                row_width = sum(node.width for node in nodes) + self.H_GAP * max(0, len(nodes) - 1)
                row_height = max(node.height for node in nodes)
                rows.append((level, nodes, row_width, row_height))
                canvas_width = max(canvas_width, row_width)
            y = self.MARGIN
            for level, nodes, row_width, row_height in rows:
                x = self.MARGIN + (canvas_width - row_width) / 2.0
                for node in nodes:
                    node.x = x
                    node.y = y + (row_height - node.height) / 2.0
                    x += node.width + self.H_GAP
                y += row_height + self.V_GAP
            width = canvas_width + self.MARGIN * 2
            height = y - self.V_GAP + self.MARGIN
            if self.graph.direction == "BT":
                for node in self.graph.nodes.values():
                    node.y = height - self.MARGIN - node.y - node.height
        else:
            columns = []
            canvas_height = 0
            for level in sorted(by_level):
                nodes = by_level[level]
                col_height = sum(node.height for node in nodes) + self.V_GAP * max(0, len(nodes) - 1)
                col_width = max(node.width for node in nodes)
                columns.append((level, nodes, col_width, col_height))
                canvas_height = max(canvas_height, col_height)
            x = self.MARGIN
            for level, nodes, col_width, col_height in columns:
                y = self.MARGIN + (canvas_height - col_height) / 2.0
                for node in nodes:
                    node.x = x + (col_width - node.width) / 2.0
                    node.y = y
                    y += node.height + self.V_GAP
                x += col_width + self.H_GAP
            width = x - self.H_GAP + self.MARGIN
            height = canvas_height + self.MARGIN * 2
            if self.graph.direction == "RL":
                for node in self.graph.nodes.values():
                    node.x = width - self.MARGIN - node.x - node.width
        self.set_size_request(int(math.ceil(width)), int(math.ceil(height)))

    def _theme_colors(self):
        context = self.get_style_context()
        state = Gtk.StateFlags.NORMAL
        foreground = context.get_color(state)
        ok, base = context.lookup_color("theme_base_color")
        if not ok:
            base = Gdk.RGBA(1.0, 1.0, 1.0, 1.0)
        ok, border = context.lookup_color("borders")
        if not ok:
            border = Gdk.RGBA(foreground.red, foreground.green, foreground.blue, 0.45)
        return foreground, base, border

    def _draw_node(self, cr, node, foreground, base, border):
        fill = _rgba(node.style.get("fill"), base)
        stroke = _rgba(node.style.get("stroke"), border)
        line_width = node.style.get("stroke-width", "1.5").rstrip("px")
        try:
            line_width = max(1.0, min(5.0, float(line_width)))
        except ValueError:
            line_width = 1.5
        x, y, width, height = node.x, node.y, node.width, node.height
        if node.shape == "diamond":
            cr.move_to(x + width / 2.0, y)
            cr.line_to(x + width, y + height / 2.0)
            cr.line_to(x + width / 2.0, y + height)
            cr.line_to(x, y + height / 2.0)
            cr.close_path()
        elif node.shape == "circle":
            cr.save()
            cr.translate(x + width / 2.0, y + height / 2.0)
            cr.scale(width / 2.0, height / 2.0)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
        elif node.shape == "stadium":
            _rounded_rectangle(cr, x, y, width, height, height / 2.0)
        elif node.shape == "rounded":
            _rounded_rectangle(cr, x, y, width, height, 10)
        else:
            _rounded_rectangle(cr, x, y, width, height, 3)
        _set_rgba(cr, fill)
        cr.fill_preserve()
        _set_rgba(cr, stroke)
        cr.set_line_width(line_width)
        cr.stroke()

        layout = self.create_pango_layout(node.label)
        layout.set_alignment(Pango.Alignment.CENTER)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_width(int(max(40, width - 24) * Pango.SCALE))
        text_width, text_height = layout.get_pixel_size()
        text_color = _contrast_color(fill, foreground) if node.style.get("fill") else foreground
        _set_rgba(cr, text_color)
        cr.move_to(x + (width - text_width) / 2.0, y + (height - text_height) / 2.0)
        PangoCairo.show_layout(cr, layout)

    def _edge_points(self, source, target):
        direction = self.graph.direction
        if direction in ("TD", "TB") and target.y >= source.y + source.height:
            return ((source.x + source.width / 2.0, source.y + source.height),
                    (target.x + target.width / 2.0, target.y), True)
        if direction == "BT" and target.y + target.height <= source.y:
            return ((source.x + source.width / 2.0, source.y),
                    (target.x + target.width / 2.0, target.y + target.height), True)
        if direction == "LR" and target.x >= source.x + source.width:
            return ((source.x + source.width, source.y + source.height / 2.0),
                    (target.x, target.y + target.height / 2.0), True)
        if direction == "RL" and target.x + target.width <= source.x:
            return ((source.x, source.y + source.height / 2.0),
                    (target.x + target.width, target.y + target.height / 2.0), True)
        if direction in ("TD", "TB", "BT"):
            return ((source.x + source.width, source.y + source.height / 2.0),
                    (target.x + target.width, target.y + target.height / 2.0), False)
        return ((source.x + source.width / 2.0, source.y + source.height),
                (target.x + target.width / 2.0, target.y + target.height), False)

    def _draw_arrow(self, cr, start, end, dotted, color, direct=True):
        x1, y1 = start
        x2, y2 = end
        vertical = self.graph.direction in ("TD", "TB", "BT")
        cr.save()
        _set_rgba(cr, color)
        cr.set_line_width(1.5)
        if dotted:
            cr.set_dash([6.0, 5.0])
        cr.move_to(x1, y1)
        if direct and vertical:
            mid = (y1 + y2) / 2.0
            cr.curve_to(x1, mid, x2, mid, x2, y2)
            tangent = (0.0, y2 - mid)
        elif direct and not vertical:
            mid = (x1 + x2) / 2.0
            cr.curve_to(mid, y1, mid, y2, x2, y2)
            tangent = (x2 - mid, 0.0)
        else:
            offset = 42.0
            cr.curve_to(x1 + offset, y1 + offset, x2 + offset, y2 - offset, x2, y2)
            tangent = (-offset, offset)
        cr.stroke()
        cr.set_dash([])
        dx, dy = tangent
        if abs(dx) + abs(dy) < 0.1:
            dx, dy = x2 - x1, y2 - y1
        angle = math.atan2(dy, dx)
        length = 8.0
        cr.move_to(x2, y2)
        cr.line_to(x2 - length * math.cos(angle - 0.45), y2 - length * math.sin(angle - 0.45))
        cr.line_to(x2 - length * math.cos(angle + 0.45), y2 - length * math.sin(angle + 0.45))
        cr.close_path()
        cr.fill()
        cr.restore()

    def _draw_edge_label(self, cr, edge, start, end, foreground, base):
        if not edge.label:
            return
        layout = self.create_pango_layout(edge.label)
        layout.set_alignment(Pango.Alignment.CENTER)
        width, height = layout.get_pixel_size()
        x = (start[0] + end[0] - width) / 2.0
        y = (start[1] + end[1] - height) / 2.0
        _set_rgba(cr, base, 0.92)
        _rounded_rectangle(cr, x - 4, y - 2, width + 8, height + 4, 3)
        cr.fill()
        _set_rgba(cr, foreground)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    def _on_draw(self, _widget, cr):
        foreground, base, border = self._theme_colors()
        for edge in self.graph.edges:
            source = self.graph.nodes[edge.source]
            target = self.graph.nodes[edge.target]
            start, end, direct = self._edge_points(source, target)
            self._draw_arrow(cr, start, end, edge.dotted, border, direct=direct)
            self._draw_edge_label(cr, edge, start, end, foreground, base)
        for node in self.graph.nodes.values():
            self._draw_node(cr, node, foreground, base, border)
        return False
