# encoding: utf-8
from __future__ import division, print_function, unicode_literals
import objc, math, traceback
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




class showTrueTypeCurves(ReporterPlugin):

	@objc.python_method 
	def settings(self):
		self.menuName = Glyphs.localize({
			'en': u'TrueType Curves',
			'pt': u'Curvas TrueType',
		})
		self.thisMenuTitle = {"name": u"%s:" % self.menuName, "action": None }
		self.masterIds = []


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
		layer = Glyphs.font.selectedLayers[0]
		self.masterIds = self.getMasterIDs(layer)
		scale = self.getScale()
		handleSize = self.getHandleSize()
		glyph = layer.parent
		
		if layer.layerId not in self.masterIds:
			return

		if not layer.paths:
			return
		
		for p, path in enumerate(layer.paths):
			dummyPath = path.copy()
			dummyPath.convertToQuadratic()
			self.drawTrueTypeCurves(dummyPath, scale)


	@objc.python_method 
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
