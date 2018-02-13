# Copyright (c) 2018 Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import c4d
import os
import re
import sys


# ============================================================================
# Helper Classes
# ============================================================================

class DialogOpenerCommand(c4d.plugins.CommandData):
  """

  """

  def __init__(self, dlg_factory, dlgtype=c4d.DLG_TYPE_ASYNC, *open_args, **open_kwargs):
    super(DialogOpenerCommand, self).__init__()
    self.dlg_factory = dlg_factory
    self.open_args = (dlgtype,) + open_args
    self.open_kwargs = open_kwargs
    self.dlg = None

  def Execute(self, doc):
    if not self.dlg: self.dlg = self.dlg_factory()
    self.dlg.Open(*self.open_args, **self.open_kwargs)
    return True

  def Register(self, plugin_id, name, info=0, icon=None, help=''):
    return c4d.plugins.RegisterCommandPlugin(
      plugin_id, name, info, icon, help, self)


class BaseDialog(c4d.gui.GeDialog):
  """
  A new base class for Cinema 4D dialogs that provides a bunch of useful
  methods for managing widgets.
  """

  def __init__(self):
    super(BaseDialog, self).__init__()
    self.__widgets = {}
    self.__reverse_cache = {}
    self.__idcounter = 9000000

  def AllocId(self):
    """
    Allocates a new ID. Used for widgets that require more than one real widget.
    """

    result = self.__idcounter
    self.__idcounter += 1
    return result

  def ReverseMapId(self, param_id):
    """
    Reverse-maps a real parameter ID to the ID of a virtual widget. If there
    is no virtual widget that allocated *param_id*, returns (None, param_id).
    If a widget has been found that uses *param_id*, returns (name, widget_id).
    """

    try:
      return self.__reverse_cache[param_id]
    except KeyError:
      result = None
      for widget_id, widget in self.__widgets.items():
        for key in widget:
          if key.startswith('id.') and widget[key] == param_id:
            result = key[3:], widget_id
            break
        if result: break
      if not result:
        result = (None, param_id)
      self.__reverse_cache[param_id] = result
      return result

  def __FileSelectorCallback(self, widget, event):
    if event['type'] == 'command' and event['param'] == widget['id.button']:
      flags = {
        'load': c4d.FILESELECT_LOAD,
        'save': c4d.FILESELECT_SAVE,
        'directory': c4d.FILESELECT_DIRECTORY
      }[widget['fileselecttype']]
      path = c4d.storage.LoadDialog(flags=flags)
      if path:
        self.SetString(widget['id.string'], path)
      return True

  def AddFileSelector(self, param_id, flags, type='load'):
    if type not in ('load', 'save', 'directory'):
      raise ValueError('invalid type: {!r}'.format(type))
    widget = {
      'type': 'fileselector',
      'id.string': self.AllocId(),
      'id.button': self.AllocId(),
      'callback': self.__FileSelectorCallback,
      'fileselecttype': type
    }
    self.__widgets[param_id] = widget
    self.GroupBegin(0, flags, 2, 0)
    self.AddEditText(widget['id.string'], c4d.BFH_SCALEFIT | c4d.BFV_FIT)
    self.AddButton(widget['id.button'], c4d.BFH_CENTER | c4d.BFV_CENTER, name='...')
    self.GroupEnd()

  def GetFileSelectorString(self, param_id):
    return self.GetString(self.__widgets[param_id]['id.string'])

  def SetFileSelectorString(self, param_id, *args, **kwargs):
    self.SetString(self.__widgets[param_id]['id.string'], *args, **kwargs)

  def AddLinkBoxGui(self, param_id, flags, minw=0, minh=0, customdata=None):
    if customdata is None:
      customdata = c4d.BaseContainer()
    elif isinstance(customdata, dict):
      bc = c4d.BaseContainer()
      for key, value in customdata.items():
        bc[key] = value
      customdata = bc
    elif not isinstance(customdata, c4d.BaseContainer):
      raise TypeError('expected one of {NoneType,dict,c4d.BaseContainer}')
    widget = {
      'type': 'linkbox',
      'gui': self.AddCustomGui(param_id, c4d.CUSTOMGUI_LINKBOX, "", flags, minw, minh, customdata)
    }
    self.__widgets[param_id] = widget
    return widget['gui']

  def GetLink(self, param_id, doc=None, instance=0):
    return self.__widgets[param_id]['gui'].GetLink(doc, instance)

  def SetLink(self, param_id, obj):
    self.__widgets[param_id]['gui'].SetLink(obj)

  # c4d.gui.GeDialog

  def Command(self, param, bc):
    event = {'type': 'command', 'param': param, 'bc': bc}
    for widget in self.__widgets.values():
      callback = widget.get('callback')
      if callback:
        if callback(widget, event):
          return True
    return False


# ============================================================================
# UserData to Description Resource Converter
# ============================================================================

class UserDataToDescriptionResourceConverterDialog(BaseDialog):
  """
  Implements the User Interface to convert an object's UserData to a
  Cinema 4D description resource.

                               MAIN
  /----------------------------------------------------------------\\
  |                                          |                     |
  |    MAIN/LEFT/PARAMS                      |                     |
  |                                          |     MAIN/RIGHT      |
  |------------------------------------------|                     |
  |   MAIN/LEFT/BUTTONS                      |                     |
  \\---------------------------------------------------------------/
  """

  ID_PLUGIN_NAME = 1000
  ID_ICON_FILE = 1001
  ID_RESOURCE_NAME = 1002
  ID_ID_PREFIX = 1003
  ID_DIRECTORY = 1004
  ID_LINK = 1005
  ID_CREATE = 1006
  ID_CANCEL = 1007
  ID_FILELIST_GROUP = 1008

  def update_filelist(self):
    resource_prefix = 'O'
    plugin_name = self.GetString(self.ID_PLUGIN_NAME)
    link = self.GetLink(self.ID_LINK)
    if link:
      if link.CheckType(c4d.Obase): resource_prefix = 'O'
      elif link.CheckType(c4d.Tbase): resource_prefix = 'T'
      elif link.CheckType(c4d.Xbase): resource_prefix = 'X'
      else: resource_prefix = ''
    if not plugin_name:
      plugin_name = (link.GetName() if link else None) or 'My Plugin'
    resource_name = self.GetString(self.ID_RESOURCE_NAME)
    if not resource_name:
      resource_name = resource_prefix + re.sub('[^\w\d]+', '', plugin_name).lower()
    icon_file = self.GetFileSelectorString(self.ID_ICON_FILE)
    parent_dir = os.path.basename(self.GetFileSelectorString(self.ID_DIRECTORY)) or plugin_name

    fmt = lambda s: s.format(**sys._getframe(1).f_locals)
    self.LayoutFlushGroup(self.ID_FILELIST_GROUP)
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('{parent_dir}/'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('  res/'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('    description/'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('      {resource_name}.h'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('      {resource_name}.res'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('    strings_us/'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('      description/'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('        {resource_name}.str'))
    if icon_file:
      suffix = os.path.splitext(icon_file)[1]
      self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('  icons/'))
      self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('    {plugin_name}.{suffix}'))
    self.AddStaticText(0, c4d.BFH_LEFT, name=fmt('    c4d_symbols.h'))
    self.LayoutChanged(self.ID_FILELIST_GROUP)

  # c4d.gui.GeDialog

  def CreateLayout(self):
    self.SetTitle('UserData to Description Resource (.res) Converter')
    self.GroupBorderSpace(6, 6, 6, 6)
    self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 1)  # MAIN {
    self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)  # MAIN/LEFT {
    self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_FIT, 2, 0)  # MAIN/LEFT/PARAMS {
    self.AddStaticText(0, c4d.BFH_LEFT, name='Source')
    self.AddLinkBoxGui(self.ID_LINK, c4d.BFH_SCALEFIT)
    self.AddStaticText(0, c4d.BFH_LEFT, name='Plugin Name')
    self.AddEditText(self.ID_PLUGIN_NAME, c4d.BFH_SCALEFIT)
    self.AddStaticText(0, c4d.BFH_LEFT, name='Icon')
    self.AddFileSelector(self.ID_ICON_FILE, c4d.BFH_SCALEFIT, type='load')
    self.AddStaticText(0, c4d.BFH_LEFT, name='Resource Name')
    self.AddEditText(self.ID_RESOURCE_NAME, c4d.BFH_SCALEFIT)
    self.AddStaticText(0, c4d.BFH_LEFT, name='ID Prefix')
    self.AddEditText(self.ID_ID_PREFIX, c4d.BFH_SCALEFIT)
    self.AddStaticText(0, c4d.BFH_LEFT, name='Plugin Directory')
    self.AddFileSelector(self.ID_DIRECTORY, c4d.BFH_SCALEFIT, type='directory')
    self.GroupEnd()  # } MAIN/LEFT/PARAMS
    self.GroupBegin(0, c4d.BFH_CENTER, 0, 1) # MAIN/LEFT/BUTTONS {
    self.AddButton(self.ID_CREATE, c4d.BFH_CENTER, name='Create')
    self.AddButton(self.ID_CANCEL, c4d.BFH_CENTER, name='Cancel')
    self.GroupEnd()  # } MAIN/LEFT/BUTTONS
    self.GroupEnd()  # } MAIN/LEFT
    self.AddSeparatorV(0, c4d.BFV_SCALEFIT)
    self.GroupBegin(self.ID_FILELIST_GROUP, c4d.BFH_RIGHT | c4d.BFV_SCALEFIT, 1, 0) # MAIN/RIGHT {
    self.GroupEnd()  # } MAIN/RIGHT
    self.GroupEnd()  # } MAIN
    self.update_filelist()
    return True

  def Command(self, param_id, bc):
    if BaseDialog.Command(self, param_id, bc):
      return True
    # Check if anything changed that would have an influence on the filelist.
    if self.ReverseMapId(param_id)[1] in (
        self.ID_PLUGIN_NAME, self.ID_RESOURCE_NAME, self.ID_DIRECTORY,
        self.ID_LINK):
      self.update_filelist()
    return True


def main():
  DialogOpenerCommand(UserDataToDescriptionResourceConverterDialog)\
    .Register(1040648, 'UserData to .res Converter')


if __name__ == '__main__':
  main()
