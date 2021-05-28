# encoding: utf-8
from __future__ import division, print_function, unicode_literals
import objc, traceback
from GlyphsApp import *
from GlyphsApp.plugins import *
from Foundation import NSMenuItem
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




class showTrueTypeCurves(ReporterPlugin):

	@objc.python_method 
	def settings(self):
		self.menuName = Glyphs.localize({
			'en': u'TrueType Curves',
			'pt': u'Curvas TrueType',
		})
		self.thisMenuTitle = {"name": u"%s:" % self.menuName, "action": None }
		self.masterIds = []
		NSUserDefaults.standardUserDefaults().registerDefaults_({
				"com.harbortype.showTrueTypeCurves.useVariableConversion": 1,
			})
		self.lastChange = None
		self.currentLayer = None
		self.currentGlyph = None


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
					'en': u"Use variable font conversion", 
					'pt': u"Usar conversão para fontes variáveis", 
					}), 
				'action': self.toggleVariableConversion_,
				'state': Glyphs.defaults["com.harbortype.showTrueTypeCurves.useVariableConversion"],
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


	def toggleVariableConversion_(self, sender):
		self.toggleSetting_("useVariableConversion")

	
	@objc.python_method 
	def toggleSetting_(self, prefName):
		pref = "com.harbortype.showTrueTypeCurves.%s" % (prefName)
		oldSetting = bool(Glyphs.defaults[pref])
		Glyphs.defaults[pref] = int(not oldSetting)
		self.refreshView()
		self.lastChange = None


	@objc.python_method 
	def refreshView(self):
		try:
			Glyphs = NSApplication.sharedApplication()
			currentTabView = Glyphs.font.currentTab
			if currentTabView:
				currentTabView.graphicView().setNeedsDisplay_(True)
		except Exception as e:
			pass


	@objc.python_method 
	def getHandleSize(self):
		""" Get the handle size in scale """
		handleSizes = (5, 8, 12)
		handleSizeIndex = Glyphs.handleSize 
		handleSize = handleSizes[handleSizeIndex] * self.getScale() ** 0.1 # scaled diameter
		return handleSize


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
	def drawTrueTypeCurves(self, path, scale):
		radius = 2.5
		currentTab = Glyphs.font.currentTab
		origin = currentTab.selectedLayerOrigin

		# Get the nodes
		for node in path.nodes:
			nextNode = node.nextNode
			x = node.position.x
			y = node.position.y
			dx = nextNode.position.x - x
			dy = nextNode.position.y - y
			offcurvePosition = NSPoint( (x+dx) * scale + origin[0], (y+dy) * scale + origin[1] )

			# Draw line
			# NSColor.colorWithCalibratedRed_green_blue_alpha_(1, .8, .75, 1).set()
			NSColor.colorWithCalibratedRed_green_blue_alpha_(.8, .8, .8, .8).set()
			line = NSBezierPath.bezierPath()
			line.setLineWidth_(1)
			line.moveToPoint_( NSPoint( (node.position.x) * scale + origin[0], (node.position.y) * scale + origin[1] ) )
			line.lineToPoint_(offcurvePosition)
			line.stroke()
			
			if node.type != OFFCURVE:
				continue

			# Draw nodes
			circle = NSRect()
			circle.size = NSSize(radius * 2 , radius * 2)
			circle.origin = NSPoint( (node.position.x) * scale + origin[0] - radius, (node.position.y) * scale + origin[1] - radius )
			NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(circle, radius, radius).fill()
		

	@objc.python_method 
	def foregroundInViewCoords(self, layer=None): 
		""" Draw stuff on the screen """
		pass

	@objc.python_method 
	def backgroundInViewCoords(self, layer=None):
		""" Draw stuff in the background """
		
		# Execute only if there are selected layers
		if not Glyphs.font.selectedLayers:
			return
		
		layer = Glyphs.font.selectedLayers[0]
		self.masterIds = self.getMasterIDs(layer)
		scale = self.getScale()
		handleSize = self.getHandleSize()
		glyph = layer.parent
		
		if layer.layerId not in self.masterIds:
			return

		if not layer.paths:
			return

		# Only converts to quadratic if the glyph or the current layer was changed
		if glyph.lastChange != self.lastChange or layer.layerId != self.currentLayer or glyph.name != self.currentGlyph:
			if Glyphs.boolDefaults["com.harbortype.showTrueTypeCurves.useVariableConversion"]:
				dummyGlyph = glyph.duplicate()
				dummyGlyph.convertToCompatibleTrueTypeWithError_error_(0.6, None)
				self.trueTypePaths = dummyGlyph.layers[layer.layerId].paths
			else:
				self.trueTypePaths = []
				for path in layer.paths:
					dummyPath = path.copy()
					dummyPath.convertToQuadratic()
					self.trueTypePaths.append(dummyPath)
			self.lastChange = glyph.lastChange
			self.currentLayer = layer.layerId
			self.currentGlyph = glyph.name

		# Draw the quadratic paths
		for path in self.trueTypePaths:
			self.drawTrueTypeCurves(path, scale)


	@objc.python_method 
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
