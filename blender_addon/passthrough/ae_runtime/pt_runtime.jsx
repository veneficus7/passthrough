/*
 * Passthrough ExtendScript runtime.
 *
 * Concatenated into every generated .jsx by jsx_writer.py.
 *
 * ECMAScript 3 ONLY (SPEC.md 7.1). Not available here, and some of these fail
 * silently rather than loudly:
 *   let, const, arrow functions, template literals,
 *   JSON.parse / JSON.stringify,
 *   Array.prototype.forEach / map / filter / indexOf,
 *   String.prototype.trim, Object.keys
 * Use var, function () {}, string concatenation and indexed for loops.
 */

var PT_WARNINGS = [];

function ptWarn(message) {
    PT_WARNINGS[PT_WARNINGS.length] = message;
}

function ptFindComp(name) {
    var items = app.project.items;
    var i;
    for (i = 1; i <= items.length; i++) {
        if (items[i] instanceof CompItem && items[i].name === name) {
            return items[i];
        }
    }
    return null;
}

/*
 * Reuse a comp of the same name rather than piling up duplicates every time
 * the script is run, mirroring the idempotency the Blender side has.
 */
function ptEnsureComp(name, width, height, pixelAspect, duration, frameRate) {
    var comp = ptFindComp(name);
    if (comp === null) {
        return app.project.items.addComp(name, width, height, pixelAspect, duration, frameRate);
    }
    comp.width = width;
    comp.height = height;
    comp.pixelAspect = pixelAspect;
    comp.duration = duration;
    comp.frameRate = frameRate;
    return comp;
}

function ptRemoveLayer(comp, name) {
    var i;
    for (i = comp.numLayers; i >= 1; i--) {
        if (comp.layer(i).name === name) {
            comp.layer(i).remove();
        }
    }
}

/*
 * One value means a static property; more means a keyframed one. Writing a
 * single setValue avoids littering the timeline with identical keys.
 */
function ptApply(prop, times, values) {
    if (values.length === 0) {
        return;
    }
    if (values.length === 1) {
        prop.setValue(values[0]);
        return;
    }
    prop.setValuesAtTimes(times, values);
}

/* ---- footage ---------------------------------------------------------- */

function ptFindFootage(path) {
    var items = app.project.items;
    var i;
    for (i = 1; i <= items.length; i++) {
        var item = items[i];
        if (item instanceof FootageItem && item.mainSource instanceof FileSource) {
            if (item.mainSource.file !== null && item.mainSource.file.fsName === path) {
                return item;
            }
        }
    }
    return null;
}

/*
 * Import one pass as an image sequence. `path` is the FIRST frame; After
 * Effects gathers the rest of the numbered sequence itself.
 *
 * conformFrameRate matters: an imported sequence takes the frame rate from the
 * user's import preferences, not from the comp. Left alone, a 24 fps comp can
 * end up holding 30 fps footage and every pass drifts out of sync with the
 * camera.
 */
function ptImportSequence(path, frameRate, alphaPremultiplied) {
    var file = new File(path);
    if (!file.exists) {
        ptWarn("missing pass sequence: " + path);
        return null;
    }
    var existing = ptFindFootage(file.fsName);
    if (existing !== null) {
        return existing;
    }
    var options = new ImportOptions(file);
    options.sequence = true;
    var item;
    try {
        item = app.project.importFile(options);
    } catch (err) {
        ptWarn("could not import " + path + ": " + err.toString());
        return null;
    }
    try {
        if (frameRate > 0) {
            item.mainSource.conformFrameRate = frameRate;
        }
        if (alphaPremultiplied) {
            item.mainSource.alphaMode = AlphaMode.PREMULTIPLIED;
            item.mainSource.premulColor = [0, 0, 0];
        } else {
            item.mainSource.alphaMode = AlphaMode.STRAIGHT;
        }
    } catch (err2) {
        ptWarn("could not interpret " + path + ": " + err2.toString());
    }
    return item;
}

/*
 * Add one pass as a layer. Everything except the beauty is a disabled guide
 * layer: the ingredients, arranged and labelled, with no look presumed
 * (SPEC.md M4).
 */
function ptAddPassLayer(comp, name, path, isGuide, frameRate, alphaPremultiplied, note) {
    ptRemoveLayer(comp, name);
    var item = ptImportSequence(path, frameRate, alphaPremultiplied);
    if (item === null) {
        return null;
    }
    var layer = comp.layers.add(item);
    layer.name = name;
    layer.startTime = 0;
    if (note) {
        // Shows in the timeline's Comment column. A disabled guide layer with
        // no explanation is a puzzle, and the cryptomatte one renders black.
        layer.comment = note;
    }
    if (isGuide) {
        layer.guideLayer = true;
        layer.enabled = false;
    }
    return layer;
}

/* ---- 3D scene --------------------------------------------------------- */

/*
 * A null whose transform is the identity, so parenting to it changes nothing.
 *
 * That is only true when position equals anchorPoint: After Effects builds a
 * layer's transform as translate(position) * rotate * scale * translate(-anchorPoint).
 * addNull() leaves the anchor at the centre of the 100x100 null and the position
 * at the centre of the comp, which would shift every child. Both are zeroed
 * here on purpose -- the camera's alignment depends on it.
 */
function ptEnsureWorldNull(comp, name, duration) {
    ptRemoveLayer(comp, name);
    var layer = comp.layers.addNull(duration);
    layer.name = name;
    layer.threeDLayer = true;
    layer.property("Anchor Point").setValue([0, 0, 0]);
    layer.property("Position").setValue([0, 0, 0]);
    layer.property("Rotation").setValue(0);
    layer.property("Scale").setValue([100, 100, 100]);
    layer.enabled = false;
    return layer;
}

function ptAddNull(comp, name, times, positions, orientations, parent, duration) {
    ptRemoveLayer(comp, name);
    var layer = comp.layers.addNull(duration);
    layer.name = name;
    layer.threeDLayer = true;
    layer.property("Anchor Point").setValue([0, 0, 0]);
    ptApply(layer.property("Position"), times, positions);
    ptApply(layer.property("Orientation"), times, orientations);
    if (parent !== null) {
        layer.parent = parent;
    }
    return layer;
}

function ptAddCamera(comp, name, times, positions, orientations, zooms, parent) {
    ptRemoveLayer(comp, name);
    var cam = comp.layers.addCamera(name, [comp.width / 2, comp.height / 2]);
    cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
    ptApply(cam.property("Position"), times, positions);
    ptApply(cam.property("Orientation"), times, orientations);
    ptApply(cam.property("Zoom"), times, zooms);
    if (parent !== null) {
        cam.parent = parent;
    }
    return cam;
}

function ptReportWarnings() {
    if (PT_WARNINGS.length === 0) {
        return;
    }
    var text = "Passthrough finished with " + PT_WARNINGS.length + " warning(s):\n";
    var i;
    for (i = 0; i < PT_WARNINGS.length; i++) {
        text = text + "\n- " + PT_WARNINGS[i];
    }
    alert(text);
}
