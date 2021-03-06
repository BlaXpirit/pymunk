__docformat__ = "reStructuredText"

import weakref
from weakref import WeakSet
import platform
    
from . import _chipmunk_cffi
cp = _chipmunk_cffi.lib
ffi = _chipmunk_cffi.ffi    
    
from .vec2d import Vec2d
from .body import Body
from .collision_handler import CollisionHandler
from .query_info import PointQueryInfo, SegmentQueryInfo, ShapeQueryInfo
from .shapes import Shape, Circle, Poly, Segment
from .contact_point_set import ContactPointSet
from pymunk.constraint import Constraint

class Space(object):
    """Spaces are the basic unit of simulation. You add rigid bodies, shapes
    and joints to it and then step them all forward together through time.
    """
    def __init__(self, threaded=False):
        """Create a new instace of the Space. 
        
        If you set threaded=True the step function will run in threaded mode
        which might give a speedup. Note that even when you set threaded=True 
        you still have to set Space.threads=2 to actually use more than one 
        thread.        
        
        Also note that threaded mode is not available on Windows, and setting 
        threaded=True has no effect on that platform.
        """
        
        self.threaded = threaded and platform.system() != 'Windows' 
        if self.threaded:        
            self._space = ffi.gc(cp.cpHastySpaceNew(), cp.cpHastySpaceFree)
        else:
            self._space = ffi.gc(cp.cpSpaceNew(), cp.cpSpaceFree)

        self._static_body = None

        self._handlers = {} # To prevent the gc to collect the callbacks.
        self._handlers_key = 0
        self._default_handler = None

        self._post_step_callbacks = {}
        self._removed_shapes = {}

        self._shapes = {}
        self._bodies = set()
        self._static_body = None
        self._constraints = set()
        
        self._in_step = False
        self._add_later = set()
        self._remove_later = set()


    def _get_self(self):
        return self

    def _get_shapes(self):
        """A list of all the shapes added to this space 
        
        (includes both static and non-static)
        """
        return list(self._shapes.values())
    shapes = property(_get_shapes,
        doc=_get_shapes.__doc__)

    def _get_bodies(self):
        return list(self._bodies)
    bodies = property(_get_bodies,
        doc="""A list of the bodies added to this space""")

    def _get_constraints(self):
        return list(self._constraints)
    constraints = property(_get_constraints,
        doc="""A list of the constraints added to this space""")

    def _get_static_body(self):
        """A dedicated static body for the space. 
        
        You don't have to use it, but because its memory is managed 
        automatically with the space its very convenient. 
        """
        if self._static_body == None:
            b = cp.cpSpaceGetStaticBody(self._space)
            self._static_body = Body._init_with_body(b)
            self._static_body._space = self
        return self._static_body
    static_body = property(_get_static_body, doc=_get_static_body.__doc__)

    def _set_iterations(self, value):
        cp.cpSpaceSetIterations(self._space, value)
    def _get_iterations(self):
        return cp.cpSpaceGetIterations(self._space)
    iterations = property(_get_iterations, _set_iterations
        , doc="""Iterations allow you to control the accuracy of the solver.

        Defaults to 10.

        Pymunk uses an iterative solver to figure out the forces between
        objects in the space. What this means is that it builds a big list of
        all of the collisions, joints, and other constraints between the
        bodies and makes several passes over the list considering each one
        individually. The number of passes it makes is the iteration count,
        and each iteration makes the solution more accurate. If you use too
        many iterations, the physics should look nice and solid, but may use
        up too much CPU time. If you use too few iterations, the simulation
        may seem mushy or bouncy when the objects should be solid. Setting
        the number of iterations lets you balance between CPU usage and the
        accuracy of the physics. Pymunk's default of 10 iterations is
        sufficient for most simple games.
        """)


    def _set_gravity(self, gravity_vector):
        cp.cpSpaceSetGravity(self._space, gravity_vector)
    def _get_gravity(self):
        return Vec2d(cp.cpSpaceGetGravity(self._space))
    gravity = property(_get_gravity, _set_gravity
        , doc="""Global gravity applied to the space.

        Defaults to (0,0). Can be overridden on a per body basis by writing
        custom integration functions.
        """)

    def _set_damping(self, damping):
        cp.cpSpaceSetDamping(self._space, damping)
    def _get_damping(self):
        return cp.cpSpaceGetDamping(self._space)
    damping = property(_get_damping, _set_damping
        , doc="""Amount of simple damping to apply to the space.

        A value of 0.9 means that each body will lose 10% of its velocity per
        second. Defaults to 1. Like gravity, it can be overridden on a per
        body basis.
        """)

    def _set_idle_speed_threshold(self, idle_speed_threshold):
        cp.cpSpaceSetIdleSpeedThreshold(self._space, idle_speed_threshold)
    def _get_idle_speed_threshold(self):
        return cp.cpSpaceGetIdleSpeedThreshold(self._space)
    idle_speed_threshold = property(_get_idle_speed_threshold
        , _set_idle_speed_threshold
        , doc="""Speed threshold for a body to be considered idle.

        The default value of 0 means the space estimates a good threshold
        based on gravity.
        """)

    def _set_sleep_time_threshold(self, sleep_time_threshold):
        cp.cpSpaceSetSleepTimeThreshold(self._space, sleep_time_threshold)
    def _get_sleep_time_threshold(self):
        return cp.cpSpaceGetSleepTimeThreshold(self._space)
    sleep_time_threshold = property(_get_sleep_time_threshold
        , _set_sleep_time_threshold
        , doc="""Time a group of bodies must remain idle in order to fall
        asleep.

        The default value of `inf` disables the sleeping algorithm.
        """)

    def _set_collision_slop(self, collision_slop):
        cp.cpSpaceSetCollisionSlop(self._space, collision_slop)
    def _get_collision_slop(self):
        return cp.cpSpaceGetCollisionSlop(self._space)
    collision_slop = property(_get_collision_slop
        , _set_collision_slop
        , doc="""Amount of overlap between shapes that is allowed.

        To improve stability, set this as high as you can without noticable
        overlapping. It defaults to 0.1.
        """)

    def _set_collision_bias(self, collision_bias):
        cp.cpSpaceSetCollisionBias(self._space, collision_bias)
    def _get_collision_bias(self):
        return cp.cpSpaceGetCollisionBias(self._space)
    collision_bias = property(_get_collision_bias
        , _set_collision_bias
        , doc="""Determines how fast overlapping shapes are pushed apart.

        Pymunk allows fast moving objects to overlap, then fixes the overlap
        over time. Overlapping objects are unavoidable even if swept
        collisions are supported, and this is an efficient and stable way to
        deal with overlapping objects. The bias value controls what
        percentage of overlap remains unfixed after a second and defaults
        to ~0.2%. Valid values are in the range from 0 to 1, but using 0 is
        not recommended for stability reasons. The default value is
        calculated as cpfpow(1.0f - 0.1f, 60.0f) meaning that pymunk attempts
        to correct 10% of error ever 1/60th of a second.

        ..Note::
            Very very few games will need to change this value.
        """)

    def _set_collision_persistence(self, collision_persistence):
        cp.cpSpaceSetCollisionPersistence(self._space, collision_persistence)
    def _get_collision_persistence(self):
        return cp.cpSpaceGetCollisionPersistence(self._space)
    collision_persistence = property(_get_collision_persistence
        , _set_collision_persistence
        , doc="""The number of frames the space keeps collision solutions
        around for.

        Helps prevent jittering contacts from getting worse. This defaults
        to 3.

        ..Note::
            Very very few games will need to change this value.
        """)

    def _get_current_time_step(self):
        return cp.cpSpaceGetCurrentTimeStep(self._space)
    current_time_step = property(_get_current_time_step,
        doc="""Retrieves the current (if you are in a callback from
        Space.step()) or most recent (outside of a Space.step() call)
        timestep.
        """)

    def add(self, *objs):
        """Add one or many shapes, bodies or joints to the space

        Unlike Chipmunk and earlier versions of pymunk its now allowed to add
        objects even from a callback during the simulation step. However, the
        add will not be performed until the end of the step.
        """

        if self._in_step:
            self._add_later.add(objs)
            return

        for o in objs:
            if isinstance(o, Body):
                self._add_body(o)
            elif isinstance(o, Shape):
                self._add_shape(o)
            elif isinstance(o, Constraint):
                self._add_constraint(o)
            else:
                for oo in o:
                    self.add(oo)

    def remove(self, *objs):
        """Remove one or many shapes, bodies or constraints from the space

        Unlike Chipmunk and earlier versions of pymunk its now allowed to
        remove objects even from a callback during the simulation step.
        However, the removal will not be performed until the end of the step.

        .. Note::
            When removing objects from the space, make sure you remove any
            other objects that reference it. For instance, when you remove a
            body, remove the joints and shapes attached to it.
        """

        if self._in_step:
            self._remove_later.add(objs)
            return

        for o in objs:
            if isinstance(o, Body):
                self._remove_body(o)
            elif isinstance(o, Shape):
                self._remove_shape(o)
            elif isinstance(o, Constraint):
                self._remove_constraint(o)
            else:
                for oo in o:
                    self.remove(oo)

    def _add_shape(self, shape):
        """Adds a shape to the space"""
        assert shape._get_shapeid() not in self._shapes, "shape already added to space"
        shape._space = weakref.proxy(self)
        self._shapes[shape._get_shapeid()] = shape
        cp.cpSpaceAddShape(self._space, shape._shape)

    def _add_body(self, body):
        """Adds a body to the space"""
        assert body not in self._bodies, "body already added to space"
        body._space = weakref.proxy(self)
        self._bodies.add(body)
        cp.cpSpaceAddBody(self._space, body._body)

    def _add_constraint(self, constraint):
        """Adds a constraint to the space"""
        assert constraint not in self._constraints, "constraint already added to space"
        self._constraints.add(constraint)
        cp.cpSpaceAddConstraint(self._space, constraint._constraint)

    def _remove_shape(self, shape):
        """Removes a shape from the space"""
        self._removed_shapes[shape._get_shapeid()] = shape
        del self._shapes[shape._get_shapeid()]
        cp.cpSpaceRemoveShape(self._space, shape._shape)
    def _remove_body(self, body):
        """Removes a body from the space"""
        body._space = None
        self._bodies.remove(body)
        cp.cpSpaceRemoveBody(self._space, body._body)
    def _remove_constraint(self, constraint):
        """Removes a constraint from the space"""
        self._constraints.remove(constraint)
        cp.cpSpaceRemoveConstraint(self._space, constraint._constraint)

    def reindex_shape(self, shape):
        """Update the collision detection data for a specific shape in the
        space.
        """
        cp.cpSpaceReindexShape(self._space, shape._shape)

    def reindex_shapes_for_body(self, body):
        """Reindex all the shapes for a certain body."""
        cp.cpSpaceReindexShapesForBody(self._space, body._body)

    def reindex_static(self):
        """Update the collision detection info for the static shapes in the
        space. You only need to call this if you move one of the static shapes.
        """
        cp.cpSpaceReindexStatic(self._space)

    def _get_threads(self):
        if self.threaded:
            return int(cp.cpHastySpaceGetThreads(self._space))
        return 1 

    def _set_threads(self, n):
        if self.threaded:
            cp.cpHastySpaceSetThreads(self._space, n)
    threads=property(_get_threads, _set_threads, 
        doc="""The number of threads to use for running the step function. 
        
        Only valid on platforms other than Windows and when the Space was 
        created with threaded=True. Currently the max limit is 2, setting a
        higher value wont have any effect. The default is 1 regardless if the 
        Space was created with threaded=True, to keep determinism in the 
        simulation.
        """)


    def step(self, dt):
        """Update the space for the given time step. 
        
        Using a fixed time step is highly recommended. Doing so will increase 
        the efficiency of the contact persistence, requiring an order of 
        magnitude fewer iterations to resolve the collisions in the usual case.
        """

        self._in_step = True
        if self.threaded:
            cp.cpHastySpaceStep(self._space, dt)
        else:
            cp.cpSpaceStep(self._space, dt)
        self._removed_shapes = {}
        self._in_step = False

        for objs in self._add_later:
            self.add(objs)
        self._add_later.clear()

        for objs in self._remove_later:
            self.remove(objs)
        self._remove_later.clear()
        
        for key in self._post_step_callbacks:
            self._post_step_callbacks[key](self)  
        
        self._post_step_callbacks = {}  


    def add_collision_handler(self, collision_type_a, collision_type_b):
        """Return the CollisionHandler for collisions between objects ot
        type collision_type_a and collision_type_b.

        Fill the desired collision callback functions, for details see the
        CollisionHandler object.

        Whenever shapes with collision types (Shape.collision_type) a and b
        collide, this handler will be used to process the collision events.
        When a new collision handler is created, the callbacks will all be
        set to builtin callbacks that perform the default behavior (call the
        wildcard handlers, and accept all collisions).
        """
        
        key = (collision_type_a, collision_type_b) 
        if key in self._handlers:
            return self._handlers[key]
        
        h = cp.cpSpaceAddCollisionHandler(self._space, collision_type_a, collision_type_b)
        ch = CollisionHandler(h, self)
        self._handlers[key] = ch
        return ch
        
        p = h.contents.userData
        if p == None:
            p = self._handlers_key
            self._handlers_key += 1
            self._handlers[p] = CollisionHandler(h, self)

        return self._handlers[p]

    def add_wildcard_collision_handler(self, collision_type_a):
        """Add a wildcard collision handler for given collision type.

        This handler will be used any time an object with this type collides
        with another object, regardless of its type. A good example is a
        projectile that should be destroyed the first time it hits anything.
        There may be a specific collision handler and two wildcard handlers.
        It's up to the specific handler to decide if and when to call the
        wildcard handlers and what to do with their return values. (See
        Arbiter.call_wildcard*())

        When a new wildcard handler is created, the callbacks will all be
        set to builtin callbacks that perform the default behavior. (accept
        all collisions in begin() and pre_solve(), or do nothing for
        post_solve() and separate().
        """

        if collision_type_a in self._handlers:
            return self._handlers[collision_type_a]
            
        h = cp.cpSpaceAddWildcardHandler(self._space, collision_type_a)
        ch = CollisionHandler(h, self)
        self._handlers[collision_type_a] = ch
        return ch
        
        
        return CollisionHandler(h, self)
        p = h.contents.userData
        if p == None:
            p = self._handlers_key
            self._handlers_key += 1
            self._handlers[p] = CollisionHandler(h, self)

        return self._handlers[p]

    def add_default_collision_handler(self):
        """Return a reference to the default collision handler or that is
        used to process all collisions that don't have a more specific
        handler.

        The default behavior for each of the callbacks is to call
        the wildcard handlers, ANDing their return values together if
        applicable.
        """
        if None in self._handlers:
            return self._handlers[None]
        
        _h = cp.cpSpaceAddDefaultCollisionHandler(self._space)
        h = CollisionHandler(_h, self)
        self._handlers[None] = h
        return h
        
        p = h.contents.userData
        if p == None:
            p = self._handlers_key
            self._handlers_key += 1
            self._handlers[p] = CollisionHandler(h, self)

        return self._handlers[p]

    def add_post_step_callback(self, callback_function, key, *args, **kwargs):
        """Add a function to be called last in the next simulation step.

        Post step callbacks are registered as a function and an object used as
        a key. You can only register one post step callback per object.

        This function was more useful with earlier versions of pymunk where
        you weren't allowed to use the add and remove methods on the space
        during a simulation step. But this function is still available for
        other uses and to keep backwards compatibility.

        .. Note::
            If you remove a shape from the callback it will trigger the
            collision handler for the 'separate' event if it the shape was
            touching when removed.

        :Parameters:
            callback_function : ``func(space, key, *args, **kwargs)``
                The callback function.
            obj : Any object
                This object is used as a key, you can only have one callback
                for a single object. It is passed on to the callback function.
            args
                Optional parameters passed to the callback function.
            kwargs
                Optional keyword parameters passed on to the callback function.

        :Return:
            True if key was not previously added, False otherwise
        """

        if key in self._post_step_callbacks:
            return False
        
        def f(x):
            callback_function(self, key, *args, **kwargs)
            
        self._post_step_callbacks[key] = f
        return True
        
    def point_query(self, point, max_distance, shape_filter):
        """Query space at point for shapes within the given distance range.

        Return a list of `PointQueryInfo`.

        The filter is applied to the query and follows the same rules as the
        collision detection. Sensor shapes are included. If a maxDistance of
        0.0 is used, the point must lie inside a shape. Negative max_distance
        is also allowed meaning that the point must be a under a certain
        depth within a shape to be considered a match.

        :Parameters:
            point : (x,y) or `Vec2d`
                Define where to check for collision in the space.
            max_distnace : int
                Match only within this distance.
            shape_filter : ShapeFilter
                Only pick shapes matching the filter.
        """

        self.__query_hits = []
        
        @ffi.callback("void (*cpSpacePointQueryFunc)"
            "(cpShape *shape, cpVect point, cpFloat distance, cpVect gradient, void *data)")
        def cf(_shape, point, distance, gradient, data):
            # space = ffi.from_handle(data)
            shape = self._get_shape(_shape)
            p = PointQueryInfo(shape, Vec2d(point), distance, Vec2d(gradient))
            self.__query_hits.append(p)
            
        data = ffi.new_handle(self)
        cp.cpSpacePointQuery(self._space, point, max_distance, shape_filter, cf, data)
        return self.__query_hits

    def _get_shape(self, _shape):
        if not bool(_shape):
            return None

        shapeid = cp.cpShapeGetUserData(_shape)
        #return self._shapes[hashid_private]
        if shapeid in self._shapes:
            shape = self._shapes[shapeid]
        elif shapeid in self._removed_shapes:
            shape = self._removed_shapes[shapeid]
        else:
            shape = None
        return shape

    def point_query_nearest(self, point, max_distance, shape_filter):
        """Query space at point the nearest shape within the given distance
        range.

        Return a `PointQueryInfo` or None if nothing was hit.

        The filter is applied to the query and follows the same rules as the
        collision detection. Sensor shapes are included. If a maxDistance of
        0.0 is used, the point must lie inside a shape. Negative max_distance
        is also allowed meaning that the point must be a under a certain
        depth within a shape to be considered a match.

        :Parameters:
            point : (x,y) or `Vec2d`
                Define where to check for collision in the space.
            max_distance : int
                Match only within this distance.
            shape_filter : ShapeFilter
                Only pick shapes matching the filter.
        """
        info = ffi.new("cpPointQueryInfo *")
        _shape = cp.cpSpacePointQueryNearest(
            self._space, 
            point, max_distance, 
            shape_filter, info)
        
        shape = self._get_shape(_shape)

        if shape != None:
            return PointQueryInfo(
                shape, 
                Vec2d(info.point), 
                info.distance, 
                Vec2d(info.gradient))
        return None


    def segment_query(self, start, end, radius, shape_filter):
        """Query space along the line segment from start to end with the
        given radius.

        The filter is applied to the query and follows the same rules as the
        collision detection. Sensor shapes are included.

        :Return:
            [`SegmentQueryInfo`] - One SegmentQueryInfo object for each hit.
        """

        self.__query_hits = []
        
        @ffi.callback("void (*cpSpaceSegmentQueryFunc)"
            "(cpShape *shape, cpVect point, cpVect normal, cpFloat alpha,"
            " void *data)")
        def cf(_shape, point, normal, alpha, data):
            shape = self._get_shape(_shape)
            p = SegmentQueryInfo(shape, Vec2d(point), Vec2d(normal), alpha)
            self.__query_hits.append(p)
            
        data = ffi.new_handle(self)
        cp.cpSpaceSegmentQuery(self._space, start, end, radius, shape_filter, cf, data)
        return self.__query_hits

    def segment_query_first(self, start, end, radius,  shape_filter):
        """Query space along the line segment from start to end with the
        given radius.

        The filter is applied to the query and follows the same rules as the
        collision detection. Sensor shapes are included.

        :Return:
            `SegmentQueryInfo` - SegmentQueryInfo object or None if nothing
            was hit.
        """
        info = ffi.new("cpSegmentQueryInfo *")
        _shape = cp.cpSpaceSegmentQueryFirst(
            self._space, 
            start, end, 
            radius, shape_filter, 
            info)

        shape = self._get_shape(_shape)
        if shape != None:
            return SegmentQueryInfo(
                shape, 
                Vec2d(info.point), 
                Vec2d(info.normal), 
                info.alpha)
        return None


    def bb_query(self, bb, shape_filter):
        """Query space to find all shapes near bb.

        The filter is applied to the query and follows the same rules as the
        collision detection. Sensor shapes are included.

        Returns a list of shapes hit.
        """

        self.__query_hits = []
        @ffi.callback("typedef void (*cpSpaceBBQueryFunc)"
            "(cpShape *shape, void *data)")
        def cf(_shape, data):
            shape = self._get_shape(_shape)
            self.__query_hits.append(shape)
        
        data = ffi.new_handle(self)
        cp.cpSpaceBBQuery(self._space, bb._bb[0], shape_filter, cf, data)
        return self.__query_hits


    def shape_query(self, shape):
        """Query a space for any shapes overlapping the given shape

        Returns a list of shapes.
        """

        self.__query_hits = []
        @ffi.callback("typedef void (*cpSpaceShapeQueryFunc)"
            "(cpShape *shape, cpContactPointSet *points, void *data)")
        def cf(_shape, _points, _data):
            shape = self._get_shape(_shape)
            point_set = ContactPointSet._from_cp(_points)
            info = ShapeQueryInfo(shape, point_set)
            self.__query_hits.append(info)
            
        data = ffi.new_handle(self)
        cp.cpSpaceShapeQuery(self._space, shape._shape, cf, data)

        return self.__query_hits


    def debug_draw(self, options):
        """Debug draw the current state of the space using the supplied drawing 
        options.        

        If you use a graphics backend that is already supported, such as pygame 
        and pyglet, you can use the predefined options in their x_util modules, 
        for example pygame_util.draw_options().
        """
        h = ffi.new_handle(self)
        # we need to hold h until the end of cpSpaceDebugDraw to prevent GC
        options._options.data = h
        
        with options:
            cp.cpSpaceDebugDraw(self._space, options._options)
        
