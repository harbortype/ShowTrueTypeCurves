# encoding: utf-8
from __future__ import division, print_function, unicode_literals

import math
import traceback

import objc
from AppKit import NSApplication, NSBezierPath, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSPoint, NSRect
from Foundation import NSClassFromString, NSMenuItem, NSString, NSUserDefaults
from GlyphsApp import *
from GlyphsApp.plugins import *

###########################################################################################################
#
#
#	Reporter Plugin
#
#	Read the docs:
#	https://github.com/schriftgestalt/GlyphsSDK/tree/master/Python%20Templates/Reporter
#
#
###########################################################################################################

DEFAULT_CURVE_ERROR = 0.6  # fallback for the "TrueType Curve Error" parameter (variable font conversion)
MAX_DEVIATION = 0.7        # deviation threshold above which a layer is flagged as high-deviation
NODE_RADIUS = 2.5           # display radius of off-curve node circles (unscaled)
DEVIATION_SAMPLES_PER_UNIT = 1  # minimum sample density: one sample every 1 unit
DEVIATION_SAMPLES_MIN = 20        # floor so very short segments still get decent coverage
DEVIATION_POLYLINE_TOLERANCE = 0.01  # max gap between a TT quadratic and its sample polyline (units)




class showTrueTypeCurves(ReporterPlugin):

	@objc.python_method
	def settings(self):
		self.menuName = Glyphs.localize({
			'en': u'TrueType Curves',
			'pt': u'Curvas TrueType',
		})
		self.thisMenuTitle = {"name": u"%s:" % self.menuName, "action": None }
		NSUserDefaults.standardUserDefaults().registerDefaults_({
				"com.harbortype.showTrueTypeCurves.drawOutlines": 1,
				"com.harbortype.showTrueTypeCurves.useVariableConversion": 0,
				"com.harbortype.showTrueTypeCurves.useForPreview": 0,
			})
		self.trueTypePathsCache = {}  # {(glyphName, layerId, isBackground): (lastOperation, paths, deviation_info)}
		self._useForPreview = bool(Glyphs.defaults["com.harbortype.showTrueTypeCurves.useForPreview"])


	@objc.python_method
	def conditionalContextMenus(self):
		return [
			{
				'name': Glyphs.localize({
					'en': u"Show TrueType Curves:",
					'pt': u"Exibir Curvas TrueType:",
					}),
				'action': None,
			},
			{
				'name': Glyphs.localize({
					'en': u"Draw outlines",
					'pt': u"Desenhar contornos",
					}),
				'action': self.toggleDrawOutlines_,
				'state': Glyphs.defaults["com.harbortype.showTrueTypeCurves.drawOutlines"],
			},
			{
				'name': Glyphs.localize({
					'en': u"Use variable font conversion",
					'pt': u"Usar conversão para fontes variáveis",
					}),
				'action': self.toggleVariableConversion_,
				'state': Glyphs.defaults["com.harbortype.showTrueTypeCurves.useVariableConversion"],
			},
			{
				'name': Glyphs.localize({
					'en': u"Use TrueType outlines for preview",
					'pt': u"Usar contornos TrueType na visualização",
					}),
				'action': self.toggleUseForPreview_,
				'state': Glyphs.defaults["com.harbortype.showTrueTypeCurves.useForPreview"],
			},
			{
				'name': Glyphs.localize({
					'en': u"Find problematic TT conversions",
					'pt': u"Reportar conversões TT problemáticas",
					}),
				'action': self.reportHighDeviationGlyphs_,
			},
		]

	def addMenuItemsForEvent_toMenu_(self, event, contextMenu):
		try:
			if self.generalContextMenus:
				setUpMenuHelper(contextMenu, self.generalContextMenus, self)

			contextMenu.addItem_(NSMenuItem.separatorItem())

			for entry in self.conditionalContextMenus():
				item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
					entry["name"], entry.get("action"), "")
				item.setTarget_(self)
				if "state" in entry:
					item.setState_(entry["state"])
				contextMenu.addItem_(item)

		except Exception as e:
			print(traceback.format_exc())


	def reportHighDeviationGlyphs_(self, sender):
		font = Glyphs.font
		if not font:
			return
		masterId = font.selectedFontMaster.id
		deviations = []  # [(max_deviation, glyph_name)]
		for glyph in font.glyphs:
			layer = glyph.layers[masterId]
			if not layer or not layer.paths:
				continue
			# Always use static conversion for the font-wide scan (variable is too slow)
			psLayer = self._cornerDecomposedLayer(layer)
			ttPaths = []
			for path in psLayer.paths:
				dummyPath = path.copy()
				dummyPath.convertToQuadratic()
				ttPaths.append(dummyPath)
			dev, _, _ = self._computeLayerDeviation(psLayer, ttPaths)
			if dev >= MAX_DEVIATION:
				deviations.append((dev, glyph.name))
		if not deviations:
			Message(
				Glyphs.localize({
					'en': u"No problematic TT conversions found.",
					'pt': u"Nenhuma conversão TT problemática encontrada.",
				}),
				Glyphs.localize({
					'en': u"Find problematic TT conversions",
					'pt': u"Reportar conversões TT problemáticas",
				})
			)
			return
		deviations.sort(reverse=True)
		tab_text = "/" + "/".join(name for _, name in deviations)
		font.newTab(tab_text)

	def toggleVariableConversion_(self, sender):
		self.toggleSetting_("useVariableConversion")


	def toggleDrawOutlines_(self, sender):
		self.toggleSetting_("drawOutlines")


	def toggleUseForPreview_(self, sender):
		self.toggleSetting_("useForPreview")


	@objc.python_method
	def toggleSetting_(self, prefName):
		pref = "com.harbortype.showTrueTypeCurves.%s" % (prefName)
		oldSetting = bool(Glyphs.defaults[pref])
		Glyphs.defaults[pref] = int(not oldSetting)
		if prefName == "useForPreview":
			self._useForPreview = not oldSetting
		self.refreshView()
		self.trueTypePathsCache = {}

	@objc.python_method
	def refreshView(self):
		try:
			app = NSApplication.sharedApplication()
			currentTabView = app.font.currentTab
			if currentTabView:
				currentTabView.graphicView().setNeedsDisplay_(True)
		except Exception:
			pass


	@objc.python_method
	def getMasterIDs(self, layer):
		""" Get the masters and special layers IDs """
		masterIds = set()
		glyph = layer.parent
		for lyr in glyph.layers:
			if lyr.isSpecialLayer or lyr.layerId == lyr.associatedMasterId:
				masterIds.add(lyr.layerId)
		return list(masterIds)


	@objc.python_method
	def _getActiveTool(self):
		""" Return the active tool delegate, or None if unavailable """
		currentController = self.controller.view().window().windowController()
		if currentController:
			return currentController.toolDrawDelegate()
		return None

	def conditionsAreMetForDrawing(self):
		""" Check if the text or hand tools are active """
		tool = self._getActiveTool()
		if tool:
			textToolIsActive = tool.isKindOfClass_(NSClassFromString("GlyphsToolText"))
			handToolIsActive = tool.isKindOfClass_(NSClassFromString("GlyphsToolHand"))
			if not textToolIsActive and not handToolIsActive:
				return True
		return False


	def _isPreviewToolActive(self):
		""" Returns True if hand or text tool is active (both show TT preview) """
		tool = self._getActiveTool()
		if tool:
			handToolIsActive = tool.isKindOfClass_(NSClassFromString("GlyphsToolHand"))
			textToolIsActive = tool.isKindOfClass_(NSClassFromString("GlyphsToolText"))
			return handToolIsActive or textToolIsActive
		return False


	@objc.python_method
	def _cornerDecomposedLayer(self, layer):
		""" Return a copy of layer with corner and cap components applied to its paths, or layer itself if it has none. """
		if not layer.hasCorners():
			return layer
		layerCopy = layer.copy()
		layerCopy.parent = layer.parent  # the copy needs the font to find the _corner glyphs
		layerCopy.decomposeCorners()
		return layerCopy

	@objc.python_method
	def _cacheKey(self, layer):
		""" A background layer shares its layerId with the foreground, so the layer type is part of the key. """
		return (layer.parent.name, layer.layerId, isinstance(layer, GSBackgroundLayer))

	@objc.python_method
	def _getTrueTypePaths(self, layer):
		""" Return TT-converted paths for layer, using a per-layer cache. """
		glyph = layer.parent
		cacheKey = self._cacheKey(layer)
		lastOp, paths, deviation = self.trueTypePathsCache.get(cacheKey, (None, None, None))
		if glyph.lastOperation() != lastOp or paths is None:
			if Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.useVariableConversion"]:
				curveError = DEFAULT_CURVE_ERROR
				if Glyphs.font.customParameters["TrueType Curve Error"] is not None:
					curveError = float(Glyphs.font.customParameters["TrueType Curve Error"])
				dummyGlyph = glyph.duplicate()
				for dummyLayer in dummyGlyph.layers:
					if dummyLayer.hasCorners():
						dummyLayer.decomposeCorners()
				dummyGlyph.convertToCompatibleTrueTypeWithError_error_(curveError, None)
				paths = dummyGlyph.layers[layer.layerId].paths
				del Glyphs.font.glyphs[dummyGlyph.name]
			else:
				psLayer = self._cornerDecomposedLayer(layer)  # keep a reference, or the copy is freed before its paths are read
				paths = []
				for path in psLayer.paths:
					dummyPath = path.copy()
					dummyPath.convertToQuadratic()
					paths.append(dummyPath)
			self.trueTypePathsCache[cacheKey] = (glyph.lastOperation(), paths, None)  # deviation computed lazily
		return paths

	@objc.python_method
	def _getLayerDeviation(self, layer):
		""" Return the cached deviation_info (value, point, normal) for layer, computing it if not yet cached. """
		paths = self._getTrueTypePaths(layer)
		cacheKey = self._cacheKey(layer)
		lastOp, _, deviation_info = self.trueTypePathsCache.get(cacheKey, (None, None, None))
		if deviation_info is None:
			psLayer = self._cornerDecomposedLayer(layer)
			deviation_info = self._computeLayerDeviation(psLayer, paths)
			self.trueTypePathsCache[cacheKey] = (lastOp, paths, deviation_info)
		return deviation_info

	@objc.python_method
	def _sampleCubic(self, p0, p1, p2, p3, n):
		""" Sample a cubic Bézier at n+1 points, returns list of (x, y). """
		pts = []
		for i in range(n + 1):
			t = i / n
			u = 1.0 - t
			x = u**3*p0.x + 3*u**2*t*p1.x + 3*u*t**2*p2.x + t**3*p3.x
			y = u**3*p0.y + 3*u**2*t*p1.y + 3*u*t**2*p2.y + t**3*p3.y
			pts.append((x, y))
		return pts

	@objc.python_method
	def _sampleQuad(self, p0, p1, p2, n):
		""" Sample a quadratic Bézier at n+1 points, returns list of (x, y). """
		pts = []
		for i in range(n + 1):
			t = i / n
			u = 1.0 - t
			x = u**2*p0.x + 2*u*t*p1.x + t**2*p2.x
			y = u**2*p0.y + 2*u*t*p1.y + t**2*p2.y
			pts.append((x, y))
		return pts

	@objc.python_method
	def _quadSamples(self, p0, p1, p2):
		"""
		Compute the sample count for a quadratic Bézier so the polyline through
		its samples stays within DEVIATION_POLYLINE_TOLERANCE of the curve.
		With n even steps in t, the largest gap is |p0 - 2*p1 + p2| / (4 * n**2).
		"""
		dx = p0.x - 2*p1.x + p2.x
		dy = p0.y - 2*p1.y + p2.y
		bend = (dx*dx + dy*dy) ** 0.5
		return max(1, int(math.ceil((bend / (4 * DEVIATION_POLYLINE_TOLERANCE)) ** 0.5)))

	@objc.python_method
	def _segmentSamples(self, p0, p3):
		""" Compute an adaptive sample count based on the chord length of a segment. """
		chord = ((p3.x - p0.x)**2 + (p3.y - p0.y)**2) ** 0.5
		return max(DEVIATION_SAMPLES_MIN, int(chord * DEVIATION_SAMPLES_PER_UNIT))

	@objc.python_method
	def _pointToSegmentDistSq(self, cx, cy, a, b):
		""" Return (squared distance, nearest point) from (cx, cy) to the line segment from a to b. """
		ax, ay = a
		dx, dy = b[0] - ax, b[1] - ay
		len_sq = dx*dx + dy*dy
		t = 0.0 if len_sq == 0 else max(0.0, min(1.0, ((cx - ax)*dx + (cy - ay)*dy) / len_sq))
		px, py = ax + t*dx, ay + t*dy
		return (cx - px)**2 + (cy - py)**2, (px, py)

	@objc.python_method
	def _computeLayerDeviation(self, layer, ttPaths):
		"""
		Compute approximate max PS→TT deviation using segment-local matching.
		For each cubic segment in the PS path, the corresponding TT quadratic
		segment(s) are located via their shared on-curve endpoints (which are
		preserved by convertToQuadratic). Distance is computed only between
		matched PS/TT segments, avoiding cross-contour false matches.
		LINE segments are skipped as they convert exactly.
		Values at or above MAX_DEVIATION are exact. Below it, a segment with a
		very sharp turn can report a slightly high value.
		Returns a (value, point, normal) tuple where point is the location of
		the max deviation and normal is the unit vector perpendicular to the
		curve at that point (pointing away from the TT approximation).
		"""
		max_dev_sq = 0.0
		max_deviation_sq = MAX_DEVIATION ** 2
		max_ps_point = None
		max_tt_point = None

		for ps_path, tt_path in zip(layer.paths, ttPaths):
			tt_nodes = tt_path.nodes
			n_tt = len(tt_nodes)
			if n_tt == 0:
				continue

			# Build (rounded_x, rounded_y) → node index for all on-curve nodes in the TT path.
			# On-curve endpoints are preserved through quadratic conversion, so we can use
			# these to locate the TT segments that correspond to each cubic PS segment.
			tt_oncurve = {}
			for i, node in enumerate(tt_nodes):
				if node.type != OFFCURVE:
					key = (round(node.position.x), round(node.position.y))
					tt_oncurve[key] = i

			for node in ps_path.nodes:
				if node.type != CURVE:
					continue

				# Extract the four cubic control points
				p3 = node.position
				p2 = node.prevNode.position
				p1 = node.prevNode.prevNode.position
				p0 = node.prevNode.prevNode.prevNode.position

				# Locate the matching on-curve nodes in the TT path by endpoint position
				start_idx = tt_oncurve.get((round(p0.x), round(p0.y)))
				end_idx   = tt_oncurve.get((round(p3.x), round(p3.y)))
				if start_idx is None or end_idx is None or start_idx == end_idx:
					continue

				# Walk from start_idx+1 to end_idx (inclusive), wrapping around for closed paths
				tt_segment_nodes = []
				i = (start_idx + 1) % n_tt
				for _ in range(n_tt):
					tt_segment_nodes.append(tt_nodes[i])
					if i == end_idx:
						break
					i = (i + 1) % n_tt

				# Parse TT nodes into quadratic sub-segments.
				# One cubic can map to several quadratics; implied on-curves are inserted
				# between consecutive off-curves per TrueType spline rules.
				# The converter can also turn a nearly straight part of a curve into a LINE.
				tt_quads = []
				curr_p0 = p0
				off_pts = []
				for tt_node in tt_segment_nodes:
					if tt_node.type == OFFCURVE:
						off_pts.append(tt_node.position)
					else:
						pos = tt_node.position
						if not off_pts:
							# Straight piece, stored as a quadratic with its control point halfway
							midpoint = NSPoint((curr_p0.x + pos.x) * 0.5, (curr_p0.y + pos.y) * 0.5)
							tt_quads.append((curr_p0, midpoint, pos))
						curr = curr_p0
						for j, off in enumerate(off_pts):
							if j < len(off_pts) - 1:
								next_off = off_pts[j + 1]
								implied = NSPoint(
									(off.x + next_off.x) * 0.5,
									(off.y + next_off.y) * 0.5,
								)
								tt_quads.append((curr, off, implied))
								curr = implied
							else:
								tt_quads.append((curr, off, tt_node.position))
						off_pts = []
						curr_p0 = tt_node.position

				# Sample each quadratic just densely enough for its polyline to stay within
				# DEVIATION_POLYLINE_TOLERANCE of the curve. Shared end points are kept once.
				tt_local_samples = []
				for q0, q1, q2 in tt_quads:
					samples = self._sampleQuad(q0, q1, q2, self._quadSamples(q0, q1, q2))
					tt_local_samples.extend(samples[1:] if tt_local_samples else samples)

				if not tt_local_samples:
					continue

				# For each PS sample, find the nearest point on the TT polyline within this
				# segment's scope. Measuring to the polyline (not to the nearest sample) avoids
				# false deviations where TT samples are far apart, e.g. near long off-curves.
				# Both curves run in the same direction, so the nearest TT segment only moves
				# forward: walk ahead from the previous match while the distance keeps shrinking.
				last_seg = len(tt_local_samples) - 2
				if last_seg < 0:
					continue
				seg_max_dev_sq = 0.0
				seg_max_ps = None
				seg_max_tt = None
				j = 0
				n = self._segmentSamples(p0, p3)
				for cx, cy in self._sampleCubic(p0, p1, p2, p3, n):
					best_sq, best_pt = self._pointToSegmentDistSq(cx, cy, tt_local_samples[j], tt_local_samples[j + 1])
					while j < last_seg:
						next_sq, next_pt = self._pointToSegmentDistSq(cx, cy, tt_local_samples[j + 1], tt_local_samples[j + 2])
						if next_sq > best_sq:
							break
						best_sq, best_pt = next_sq, next_pt
						j += 1
					# On sharp turns the walk can stop too early. When the result could be
					# flagged, check the whole polyline and move the walk to the true match.
					if best_sq >= max_deviation_sq and best_sq > seg_max_dev_sq:
						for k in range(last_seg + 1):
							d_sq, pt = self._pointToSegmentDistSq(cx, cy, tt_local_samples[k], tt_local_samples[k + 1])
							if d_sq < best_sq:
								best_sq, best_pt, j = d_sq, pt, k
					if best_sq > seg_max_dev_sq:
						seg_max_dev_sq = best_sq
						seg_max_ps = (cx, cy)
						seg_max_tt = best_pt
				if seg_max_dev_sq > max_dev_sq:
					max_dev_sq = seg_max_dev_sq
					max_ps_point = seg_max_ps
					max_tt_point = seg_max_tt

		if max_ps_point and max_tt_point:
			dx = max_ps_point[0] - max_tt_point[0]
			dy = max_ps_point[1] - max_tt_point[1]
			length = (dx**2 + dy**2) ** 0.5
			normal_dir = (dx / length, dy / length) if length > 0 else (0.0, 1.0)
		else:
			normal_dir = (0.0, 1.0)
		return (max_dev_sq ** 0.5, max_ps_point or (0, 0), normal_dir)

	@objc.python_method
	def _drawDeviationLabel(self, deviation, max_point, normal_dir, scale):
		""" Draw the deviation value as a text label near the max deviation point. """
		fontSize = 10.0 / scale
		text = "%.1f" % deviation
		attrs = {
			NSFontAttributeName: NSFont.labelFontOfSize_(fontSize),
			NSForegroundColorAttributeName: NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.4, 0.0, 0.9),
		}
		offset = 20.0 / scale ** 0.5
		pt = NSPoint(
			max_point[0] + normal_dir[0] * offset,
			max_point[1] + normal_dir[1] * offset,
		)
		NSString.stringWithString_(text).drawAtPoint_withAttributes_(pt, attrs)


	@objc.python_method
	def drawTrueTypeCurves(self, path, scale):
		radiusScale = NODE_RADIUS / scale
		diameter = NODE_RADIUS * 2 / scale
		lineWidth = 1 / scale

		# Draw the outlines
		if Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.drawOutlines"]:
			outline = path.bezierPath
			outline.setLineWidth_(lineWidth)
			NSColor.colorWithCalibratedRed_green_blue_alpha_(.8, .1, .1, .8).set()
			outline.stroke()

		# Collect all handle lines and off-curve circles into two paths,
		# so they are drawn with one stroke and one fill.
		nodes = path.nodes
		positions = [node.position for node in nodes]
		isOffcurve = [node.type == OFFCURVE for node in nodes]
		handles = NSBezierPath.bezierPath()
		handles.setLineWidth_(lineWidth)
		circles = NSBezierPath.bezierPath()
		for i, pos in enumerate(positions):
			nextIndex = (i + 1) % len(positions)
			# Lines between two on-curve nodes are already part of the outline
			if isOffcurve[i] or isOffcurve[nextIndex]:
				handles.moveToPoint_(pos)
				handles.lineToPoint_(positions[nextIndex])
			if isOffcurve[i]:
				circles.appendBezierPathWithOvalInRect_(
					NSRect((pos.x - radiusScale, pos.y - radiusScale), (diameter, diameter))
				)

		NSColor.colorWithCalibratedRed_green_blue_alpha_(.8, .8, .8, .8).set()
		handles.stroke()
		circles.fill()


	@objc.python_method
	def drawTrueTypePreview(self, layer, ttPaths, graphicView, scale):
		"""
		Erase the default PS fill with the exact PS bezier shape, then redraw
		the TT-converted paths and any components using the foreground color.
		Using layer.bezierPath (exact outline shape) instead of a bounding rect
		avoids edge artifacts and handles glyphs that extend beyond their bounds.
		The PS bezier is also stroked with the canvas color to cover the thin
		anti-aliasing artifact left at its boundary after the fill.
		"""
		psBezier = layer.bezierPath
		graphicView.canvasColor().set()
		# Fill erases the default PS fill precisely
		psBezier.fill()
		# Stroke covers the anti-aliasing fringe at the PS path boundary
		psBezier.setLineWidth_(1.0 / scale)
		psBezier.stroke()
		# Draw TT paths + original components on top (no stroke)
		graphicView.foregroundColor().set()
		dummyLayer = GSLayer()
		for path in ttPaths:
			dummyLayer.shapes.append(path.copy())
		for comp in layer.components:
			dummyLayer.components.append(comp.copy())
		ttBezier = dummyLayer.bezierPath
		if ttBezier is not None:
			ttBezier.fill()

	@objc.python_method
	def _drawTrueTypePreviewForLayer(self, layer):
		""" Erase default PS fill and draw TT preview for the given layer. """
		if not self._isPreviewToolActive():
			return
		masterIds = self.getMasterIDs(layer)
		if layer.layerId not in masterIds:
			return
		if not layer.paths and not layer.components:
			return
		ttPaths = self._getTrueTypePaths(layer) if layer.paths else []
		graphicView = Glyphs.font.currentTab.graphicView()
		scale = self.getScale()
		self.drawTrueTypePreview(layer, ttPaths, graphicView, scale)

	@objc.python_method
	def foreground(self, layer=None):
		""" Draw TrueType preview on top of Glyphs' default preview. """
		if not self._useForPreview:
			return
		self._drawTrueTypePreviewForLayer(layer)

	@objc.python_method
	def foregroundInViewCoords(self, layer=None):
		""" Draw stuff on the screen """
		pass

	@objc.python_method
	def background(self, layer=None):
		""" Draw stuff in the background """

		# Execute only if there are selected layers
		if not Glyphs.font.selectedLayers:
			return

		# In preview mode all drawing happens in foreground/inactiveLayerForeground
		if self._isPreviewToolActive():
			return

		if not self.conditionsAreMetForDrawing():
			return

		masterIds = self.getMasterIDs(layer)
		scale = self.getScale()

		if layer.layerId not in masterIds:
			return

		if not layer.paths:
			return

		ttPaths = self._getTrueTypePaths(layer)

		# Draw the quadratic paths
		for path in ttPaths:
			self.drawTrueTypeCurves(path, scale)
		# Show deviation label when it exceeds the curve error threshold
		deviation, max_point, normal_dir = self._getLayerDeviation(layer)
		if deviation >= MAX_DEVIATION:
			self._drawDeviationLabel(deviation, max_point, normal_dir, scale)


	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
