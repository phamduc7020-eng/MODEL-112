#! python 2
# -*- coding: utf-8 -*-
# MODEL112 RC14 standalone launcher; run with Rhino _RunPythonScript.
import os
import io
import traceback
import Rhino
import scriptcontext as sc
try:
    rhino_major = int(Rhino.RhinoApp.Version.Major)
    if rhino_major != 7:
        raise Exception("This launcher is for Rhino 7. Current Rhino: " + str(rhino_major))
    filename = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "Model112_Rhino7_RunPythonScript.py")
    if not os.path.isfile(filename):
        raise Exception("Missing MODEL112 core: " + filename)
    sc.doc = Rhino.RhinoDoc.ActiveDoc
    form = sc.sticky.get("MODEL_112_MAIN_FORM", None)
    if form is not None and form.Visible:
        form.BringToFront()
    else:
        scope = {"__name__":"model112_runtime", "__file__":filename,
                 "__builtins__": __builtins__}
        with io.open(filename, "r", encoding="utf-8-sig") as stream:
            code = compile(stream.read(), filename, "exec")
        eval(code, scope, scope)
        open_form = scope.get("show_model_112_interface")
        if open_form is None:
            raise Exception("Cannot find show_model_112_interface")
        form = open_form()
        if form is None or not form.Visible:
            raise Exception("MODEL112 did not display a window")
except Exception:
    details = traceback.format_exc()
    Rhino.RhinoApp.WriteLine("MODEL112: " + details)
    try:
        Rhino.UI.Dialogs.ShowMessage(details, "MODEL112 - Rhino 7")
    except Exception:
        pass
    raise
