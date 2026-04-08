# encoding: utf-8
from __future__ import division, print_function, unicode_literals
import objc, traceback
from GlyphsApp import *
from GlyphsApp.plugins import *
from Foundation import NSMenuItem, NSString
from AppKit import NSFont, NSFontAttributeName, NSForegroundColorAttributeName
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
		self.trueTypePathsCache = {}  # {(glyphName, layerId): (lastOperation, paths, deviation)}


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

	@objc.python_method
	def addMenuItemsForEvent_toMenu_(self, event, contextMenu):
		'''
		The event can tell you where the user had clicked.
		'''
		try:

			if self.generalContextMenus:
				setUpMenuHelper(contextMenu, self.generalContextMenus, self)

			newSeparator = NSMenuItem.separatorItem()
			contextMenu.addItem_(newSeparator)

			contextMenus = self.conditionalContextMenus()
			if contextMenus:
				setUpMenuHelper(contextMenu, contextMenus, self)

		except Exception as e:
			NSLog(traceback.format_exc())


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
			ttPaths = []
			for path in layer.paths:
				dummyPath = path.copy()
				dummyPath.convertToQuadratic()
				ttPaths.append(dummyPath)
			dev = self._computeLayerDeviation(layer, ttPaths)
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
	def _getTrueTypePaths(self, layer):
		""" Return TT-converted paths for layer, using a per-layer cache. """
		glyph = layer.parent
		cacheKey = (glyph.name, layer.layerId)
		lastOp, paths, deviation = self.trueTypePathsCache.get(cacheKey, (None, None, None))
		if glyph.lastOperation() != lastOp or paths is None:
			if Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.useVariableConversion"]:
				curveError = DEFAULT_CURVE_ERROR
				if Glyphs.font.customParameters["TrueType Curve Error"] is not None:
					curveError = float(Glyphs.font.customParameters["TrueType Curve Error"])
				dummyGlyph = glyph.duplicate()
				dummyGlyph.convertToCompatibleTrueTypeWithError_error_(curveError, None)
				paths = dummyGlyph.layers[layer.layerId].paths
				del Glyphs.font.glyphs[dummyGlyph.name]
			else:
				paths = []
				for path in layer.paths:
					dummyPath = path.copy()
					dummyPath.convertToQuadratic()
					paths.append(dummyPath)
			self.trueTypePathsCache[cacheKey] = (glyph.lastOperation(), paths, None)  # deviation computed lazily
		return paths

	@objc.python_method
	def _getLayerDeviation(self, layer):
		""" Return the cached deviation for layer, computing it if not yet cached. """
		paths = self._getTrueTypePaths(layer)
		glyph = layer.parent
		cacheKey = (glyph.name, layer.layerId)
		lastOp, _, deviation = self.trueTypePathsCache.get(cacheKey, (None, None, None))
		if deviation is None:
			deviation = self._computeLayerDeviation(layer, paths)
			self.trueTypePathsCache[cacheKey] = (lastOp, paths, deviation)
		return deviation

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
	def _segmentSamples(self, p0, p3):
		""" Compute an adaptive sample count based on the chord length of a segment. """
		chord = ((p3.x - p0.x)**2 + (p3.y - p0.y)**2) ** 0.5
		return max(DEVIATION_SAMPLES_MIN, int(chord * DEVIATION_SAMPLES_PER_UNIT))

	@objc.python_method
	def _computeLayerDeviation(self, layer, ttPaths):
		"""
		Compute approximate max PS→TT deviation using segment-local matching.
		For each cubic segment in the PS path, the corresponding TT quadratic
		segment(s) are located via their shared on-curve endpoints (which are
		preserved by convertToQuadratic). Distance is computed only between
		matched PS/TT segments, avoiding cross-contour false matches.
		LINE segments are skipped as they convert exactly.
		"""
		max_dev_sq = 0.0

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

				# Sample count scales with chord length; computed once and shared by
				# both the TT sub-segment sampling and the cubic PS sampling below.
				n = self._segmentSamples(p0, p3)

				# Parse TT nodes into quadratic sub-segments and sample them.
				# One cubic can map to several quadratics; implied on-curves are inserted
				# between consecutive off-curves per TrueType spline rules.
				tt_local_samples = []
				curr_p0 = p0
				off_pts = []
				for tt_node in tt_segment_nodes:
					if tt_node.type == OFFCURVE:
						off_pts.append(tt_node.position)
					elif tt_node.type == QCURVE:
						if not off_pts:
							curr_p0 = tt_node.position
							continue
						curr = curr_p0
						for j, off in enumerate(off_pts):
							if j < len(off_pts) - 1:
								next_off = off_pts[j + 1]
								implied = NSPoint(
									(off.x + next_off.x) * 0.5,
									(off.y + next_off.y) * 0.5,
								)
								tt_local_samples.extend(self._sampleQuad(curr, off, implied, n))
								curr = implied
							else:
								tt_local_samples.extend(self._sampleQuad(curr, off, tt_node.position, n))
						off_pts = []
						curr_p0 = tt_node.position

				if not tt_local_samples:
					continue

				# For each PS sample, find the nearest TT sample within this segment's scope
				seg_max_dev_sq = 0.0
				for cx, cy in self._sampleCubic(p0, p1, p2, p3, n):
					min_dist_sq = min((cx - tx)**2 + (cy - ty)**2 for (tx, ty) in tt_local_samples)
					if min_dist_sq > seg_max_dev_sq:
						seg_max_dev_sq = min_dist_sq
				if seg_max_dev_sq > max_dev_sq:
					max_dev_sq = seg_max_dev_sq

		return max_dev_sq ** 0.5

	@objc.python_method
	def _drawDeviationLabel(self, deviation, layer, scale):
		""" Draw the deviation value as a text label below the glyph. """
		fontSize = 10.0 / scale
		text = "%.1f" % deviation
		attrs = {
			NSFontAttributeName: NSFont.labelFontOfSize_(fontSize),
			NSForegroundColorAttributeName: NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.4, 0.0, 0.9),
		}
		bounds = layer.bounds
		pt = NSPoint(bounds.origin.x, bounds.origin.y - fontSize * 1.5)
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

		# Get the nodes
		for node in path.nodes:
			nextNode = node.nextNode
			x = node.position.x
			y = node.position.y
			dx = nextNode.position.x - x
			dy = nextNode.position.y - y
			offcurvePosition = NSPoint(x+dx, y+dy)

			# Draw line
			NSColor.colorWithCalibratedRed_green_blue_alpha_(.8, .8, .8, .8).set()
			line = NSBezierPath.bezierPath()
			line.setLineWidth_(lineWidth)
			line.moveToPoint_( NSPoint(node.position.x, node.position.y) )
			line.lineToPoint_(offcurvePosition)
			line.stroke()

			if node.type != OFFCURVE:
				continue

			# Draw nodes
			circle = NSRect()
			circle.size = NSSize(diameter, diameter)
			circle.origin = NSPoint(node.position.x - radiusScale , node.position.y - radiusScale)
			NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(circle, radiusScale, radiusScale).fill()


	@objc.python_method
	def drawTrueTypePreview(self, paths):
		graphicView = self.controller.graphicView()
		fillColor = graphicView.foregroundColor()
		fillColor.set()
		dummyLayer = GSLayer()
		for path in paths:
			dummyLayer.paths.append(path.copy())
		dummyLayer.bezierPath.fill()


	@objc.python_method
	def _drawTrueTypePreviewForLayer(self, layer):
		""" Paint over Glyphs' default rendering and draw filled TT preview for layer. """
		if not self._isPreviewToolActive():
			return
		if not Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.useForPreview"]:
			return
		masterIds = self.getMasterIDs(layer)
		if layer.layerId not in masterIds:
			return
		if not layer.paths:
			return
		ttPaths = self._getTrueTypePaths(layer)
		if not ttPaths:
			return
		graphicView = Glyphs.font.currentTab.graphicView()
		graphicView.canvasColor().set()
		NSBezierPath.bezierPathWithRect_(layer.bounds).fill()
		self.drawTrueTypePreview(ttPaths)

	@objc.python_method
	def foreground(self, layer=None):
		""" Draw TrueType preview on top of Glyphs' default preview """
		if not Glyphs.font.selectedLayers:
			return
		self._drawTrueTypePreviewForLayer(layer)

	@objc.python_method
	def inactiveLayerForeground(self, layer=None):
		""" Draw TrueType preview for inactive layers in the tab """
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

		isPreviewTool = self._isPreviewToolActive()

		if isPreviewTool:
			if not Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.useForPreview"]:
				return
		else:
			if not self.conditionsAreMetForDrawing():
				return

		masterIds = self.getMasterIDs(layer)
		scale = self.getScale()

		if layer.layerId not in masterIds:
			return

		if not layer.paths:
			return

		ttPaths = self._getTrueTypePaths(layer)

		if not isPreviewTool:
			# Draw the quadratic paths
			for path in ttPaths:
				self.drawTrueTypeCurves(path, scale)
			# Show deviation label when it exceeds the curve error threshold
			deviation = self._getLayerDeviation(layer)
			if deviation >= MAX_DEVIATION:
				self._drawDeviationLabel(deviation, layer, scale)


	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
