# -*- coding: utf-8 -*-

"""
(C) 2014-2016 Roman Sirokov and contributors
Licensed under BSD license

http://github.com/r0x0r/pywebview/
"""

import os
import sys
import json
import logging
import threading
from ctypes import windll

base_dir = os.path.dirname(os.path.realpath(__file__))

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Threading")
clr.AddReference(os.path.join(base_dir, 'lib', 'WebBrowserInterop'))
import System.Windows.Forms as WinForms

from System import IntPtr, Int32, Func, Type #, EventHandler
from System.Threading import Thread, ThreadStart, ApartmentState
from System.Drawing import Size, Point, Icon, Color, ColorTranslator
from WebBrowserInterop import IWebBrowserInterop

from webview import OPEN_DIALOG, FOLDER_DIALOG, SAVE_DIALOG
from webview.localization import localization
from webview.win32_shared import set_ie_mode


logger = logging.getLogger(__name__)


class BrowserView:

    class JSBridge(IWebBrowserInterop):
        __namespace__ = 'BrowserView.JSBridge'
        api = None

        def call(self, func_name, param):
            function = getattr(self.api, func_name, None)
            if function is not None:
                try:
                    func_params = param if param is None else json.loads(param)
                    return function(func_params)
                except Exception as e:
                    logger.exception('Error occured while evaluating function {0}'.format(func_name))
            else:
                logger.error('Function {}() does not exist'.format(func_name))

    class BrowserForm(WinForms.Form):
        def __init__(self, title, url, width, height, resizable, fullscreen, min_size,
                     confirm_quit, background_color, webview_ready):
            self.Text = title
            self.ClientSize = Size(width, height)
            self.MinimumSize = Size(min_size[0], min_size[1])
            self.BackColor = ColorTranslator.FromHtml(background_color)

            if not resizable:
                self.FormBorderStyle = WinForms.FormBorderStyle.FixedSingle
                self.MaximizeBox = False

            # Application icon
            handle = windll.kernel32.GetModuleHandleW(None)
            icon_handle = windll.shell32.ExtractIconW(handle, sys.executable, 0)

            if icon_handle != 0:
                self.Icon = Icon.FromHandle(IntPtr.op_Explicit(Int32(icon_handle))).Clone()

            windll.user32.DestroyIcon(icon_handle)

            self.webview_ready = webview_ready

            self.web_browser = WinForms.WebBrowser()
            self.web_browser.Dock = WinForms.DockStyle.Fill
            self.web_browser.ScriptErrorsSuppressed = False
            self.web_browser.IsWebBrowserContextMenuEnabled = False
            self.web_browser.WebBrowserShortcutsEnabled = False

            self.js_bridge = BrowserView.JSBridge()
            self.web_browser.ObjectForScripting = self.js_bridge

            # HACK. Hiding the WebBrowser is needed in order to show a non-default background color. Tweaking the Visible property
            # results in showing a non-responsive control, until it is loaded fully. To avoid this, we need to disable this behaviour
            # for the default background color.
            if background_color != '#FFFFFF':
                self.web_browser.Visible = False
                self.first_load = True
            else:
                self.first_load = False

            self.cancel_back = False
            self.web_browser.PreviewKeyDown += self.on_preview_keydown
            self.web_browser.Navigating += self.on_navigating
            self.web_browser.DocumentCompleted += self.on_document_completed

            if url:
                self.web_browser.Navigate(url)

            self.Controls.Add(self.web_browser)
            self.is_fullscreen = False
            self.Shown += self.on_shown

            if confirm_quit:
                self.FormClosing += self.on_closing

            if fullscreen:
                self.toggle_fullscreen()

        def on_shown(self, sender, args):
            self.webview_ready.set()

        def on_closing(self, sender, args):
            result = WinForms.MessageBox.Show(localization["global.quitConfirmation"], self.Text,
                                              WinForms.MessageBoxButtons.OKCancel, WinForms.MessageBoxIcon.Asterisk)

            if result == WinForms.DialogResult.Cancel:
                args.Cancel = True

        def on_preview_keydown(self, sender, args):
            if args.KeyCode == WinForms.Keys.Back:
                self.cancel_back = True
            elif args.KeyCode == WinForms.Keys.Delete:
                self.web_browser.Document.ExecCommand("Delete", False, None)
            elif args.Modifiers == WinForms.Keys.Control and args.KeyCode == WinForms.Keys.C:
                self.web_browser.Document.ExecCommand("Copy", False, None)
            elif args.Modifiers == WinForms.Keys.Control and args.KeyCode == WinForms.Keys.X:
                self.web_browser.Document.ExecCommand("Cut", False, None)
            elif args.Modifiers == WinForms.Keys.Control and args.KeyCode == WinForms.Keys.V:
                self.web_browser.Document.ExecCommand("Paste", False, None)
            elif args.Modifiers == WinForms.Keys.Control and args.KeyCode == WinForms.Keys.Z:
                self.web_browser.Document.ExecCommand("Undo", False, None)
            elif args.Modifiers == WinForms.Keys.Control and args.KeyCode == WinForms.Keys.A:
                self.web_browser.Document.ExecCommand("selectAll", False, None)

        def on_navigating(self, sender, args):
            if self.cancel_back:
                args.Cancel = True
                self.cancel_back = False

        def on_document_completed(self, sender, args):
            if self.first_load:
                self.web_browser.Visible = True
                self.first_load = False

        def toggle_fullscreen(self):
            if not self.is_fullscreen:
                self.old_size = self.Size
                self.old_state = self.WindowState
                self.old_style = self.FormBorderStyle
                self.old_location = self.Location

                screen = WinForms.Screen.FromControl(self)

                self.TopMost = True
                self.FormBorderStyle = 0  # FormBorderStyle.None
                self.Bounds = WinForms.Screen.PrimaryScreen.Bounds
                self.WindowState = WinForms.FormWindowState.Maximized
                self.is_fullscreen = True

                windll.user32.SetWindowPos(self.Handle.ToInt32(), None, screen.Bounds.X, screen.Bounds.Y,
                                           screen.Bounds.Width, screen.Bounds.Height, 64)
            else:
                self.TopMost = False
                self.Size = self.old_size
                self.WindowState = self.old_state
                self.FormBorderStyle = self.old_style
                self.Location = self.old_location
                self.is_fullscreen = False

    instance = None

    def __init__(self, title, url, width, height, resizable, fullscreen, min_size, confirm_quit, background_color, webview_ready):
        BrowserView.instance = self
        self.title = title
        self.url = url
        self.width = width
        self.height = height
        self.resizable = resizable
        self.fullscreen = fullscreen
        self.min_size = min_size
        self.confirm_quit = confirm_quit
        self.webview_ready = webview_ready
        self.background_color = background_color
        self.browser = None
        self._js_result_semaphor = threading.Semaphore(0)

    def show(self):
        def start():
            app = WinForms.Application
            self.browser = BrowserView.BrowserForm(self.title, self.url, self.width,self.height, self.resizable,
                                                   self.fullscreen, self.min_size, self.confirm_quit, self.background_color, self.webview_ready)
            app.Run(self.browser)

        thread = Thread(ThreadStart(start))
        thread.SetApartmentState(ApartmentState.STA)
        thread.Start()
        thread.Join()

    def destroy(self):
        self.browser.Close()

    def get_current_url(self):
        return self.browser.web_browser.Url.AbsoluteUri

    def load_url(self, url):
        self.url = url
        self.browser.web_browser.Navigate(url)

    def load_html(self, content):
        def _load_html():
            self.browser.web_browser.DocumentText = content

        if self.browser.web_browser.InvokeRequired:
            self.browser.web_browser.Invoke(Func[Type](_load_html))
        else:
            _load_html()

    def create_file_dialog(self, dialog_type, directory, allow_multiple, save_filename):
        if not directory:
            directory = os.environ["HOMEPATH"]

        try:
            if dialog_type == FOLDER_DIALOG:
                dialog = WinForms.FolderBrowserDialog()
                dialog.RestoreDirectory = True

                result = dialog.ShowDialog(BrowserView.instance.browser)
                if result == WinForms.DialogResult.OK:
                    file_path = (dialog.SelectedPath,)
                else:
                    file_path = None
            elif dialog_type == OPEN_DIALOG:
                dialog = WinForms.OpenFileDialog()

                dialog.Multiselect = allow_multiple
                dialog.InitialDirectory = directory
                dialog.Filter = localization["windows.fileFilter.allFiles"] + " (*.*)|*.*"
                dialog.RestoreDirectory = True

                result = dialog.ShowDialog(BrowserView.instance.browser)
                if result == WinForms.DialogResult.OK:
                    file_path = tuple(dialog.FileNames)
                else:
                    file_path = None

            elif dialog_type == SAVE_DIALOG:
                dialog = WinForms.SaveFileDialog()
                dialog.Filter = localization["windows.fileFilter.allFiles"] + " (*.*)|"
                dialog.InitialDirectory = directory
                dialog.RestoreDirectory = True
                dialog.FileName = save_filename

                result = dialog.ShowDialog(BrowserView.instance.browser)
                if result == WinForms.DialogResult.OK:
                    file_path = dialog.FileName
                else:
                    file_path = None

            return file_path

        except:
            logger.exception("Error invoking {0} dialog".format(dialog_type))
            return None

    def toggle_fullscreen(self):
        self.browser.toggle_fullscreen()

    def evaluate_js(self, script):
        def _evaluate_js():
            document = self.browser.web_browser.Document
            self._js_result = document.InvokeScript('eval', (script,))
            self._js_result_semaphor.release()

        if self.browser.web_browser.InvokeRequired:
            self.browser.web_browser.Invoke(Func[Type](_evaluate_js))
        else:
            _evaluate_js()

        self._js_result_semaphor.acquire()

        return self._js_result

    def set_js_api(self, api_instance):
        with open(os.path.join(base_dir, 'js', 'api.js')) as api_js:
            self.browser.js_bridge.api = api_instance

            func_list = str([f for f in dir(api_instance) if callable(getattr(api_instance, f))])
            js_code = api_js.read() % func_list
            BrowserView.instance.evaluate_js(js_code)


def create_window(title, url, width, height, resizable, fullscreen, min_size,
                  confirm_quit, background_color, webview_ready):
    set_ie_mode()
    browser_view = BrowserView(title, url, width, height, resizable, fullscreen,
                               min_size, confirm_quit, background_color, webview_ready)
    browser_view.show()


def create_file_dialog(dialog_type, directory, allow_multiple, save_filename):
    return BrowserView.instance.create_file_dialog(dialog_type, directory, allow_multiple, save_filename)


def get_current_url():
    return BrowserView.instance.get_current_url()


def load_url(url):
    BrowserView.instance.load_url(url)


def load_html(content, base_uri):
    BrowserView.instance.load_html(content)


def toggle_fullscreen():
    BrowserView.instance.toggle_fullscreen()


def destroy_window():
    BrowserView.instance.destroy()


def evaluate_js(script):
    return BrowserView.instance.evaluate_js(script)


def set_js_api(api_object):
    BrowserView.instance.set_js_api(api_object)