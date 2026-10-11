"""
`ContextTree`, the per-slice stacks of injection contexts kept by `InjectionContextRegistry`.
"""
from typing import Hashable

from smalldi.context import InjectionContext
from smalldi.concurrency import threadsafe


class _ContextTreeNode:
    """
    One pushed context and the node it was pushed on top of.

    Nodes know their parent only, so a slice's stack is the chain of parents
    from its current node up to the root node.

    :ivar parent: the node below this one, or None for the root node
    :ivar context: the `InjectionContext` this node holds
    """
    def __init__(self, ctx: InjectionContext, parent: '_ContextTreeNode | None'):
        """
        :param ctx: the context to hold
        :param parent: the node below, or None for the root node
        """
        self.parent = parent
        self.context: InjectionContext = ctx


class ContextTree:
    """
    Tree of pushed contexts rooted at the root context, with one current node per execution slice.

    Every push creates a node whose parent is the slice's current node, or the
    root node when the slice has none, and makes it the slice's current node;
    a pop moves the slice back to the parent. A slice without a current node
    sees the root context. The nodes of different slices form branches of one
    tree, which is why `ContextAwareThread` can push the context of another
    slice on its own branch.

    All methods hold the tree's own reentrant lock through `@threadsafe`.

    :ivar root: the root `InjectionContext`
    """
    def __init__(self, root_context: InjectionContext):
        """
        :param root_context: the context every slice sees while it has nothing pushed
        """
        self.root = root_context
        self._root_node = _ContextTreeNode(root_context, None)
        self._context_slice: dict[Hashable, _ContextTreeNode] = dict()

    @threadsafe
    def current_context_for(self, slice_id: Hashable) -> InjectionContext:
        """
        Returns the context on top of a slice's stack, or the root context if the stack is empty.

        :param slice_id: the execution slice, a `threading.Thread` or an `asyncio.Task`
        :return: the slice's current `InjectionContext`
        """
        return self._context_slice.get(slice_id, self._root_node).context

    @threadsafe
    def finish_context_for(self, slice_id: Hashable, expected_node: _ContextTreeNode):
        """
        Pops a slice's current node, which must be `expected_node`, and makes its parent current.

        When the parent is the root node the slice's entry is removed, so the
        slice sees the root context again. The check runs before anything
        changes: on failure the stack is left as it was.

        :param slice_id: the execution slice
        :param expected_node: the node returned by the `add_context_for` call being undone
        :raises RuntimeError: if `expected_node` is not the slice's current node, including when
            the slice has nothing pushed
        """
        node = self._context_slice.get(slice_id)
        if node is not expected_node:
            raise RuntimeError(f"Context to finish is not the current context of slice id {slice_id}")
        if node is None:
            raise ValueError(f"Context for slice id {slice_id} not found")
        if node.parent is self._root_node:
            del self._context_slice[slice_id]
        else:
            self._context_slice[slice_id] = node.parent

    @threadsafe
    def add_context_for(self, slice_id: Hashable, ctx: InjectionContext) -> _ContextTreeNode:
        """
        Pushes a context on a slice's stack.

        :param slice_id: the execution slice
        :param ctx: the context to make current for the slice
        :return: the new node, to be passed back to `finish_context_for`
        """
        parent = self._context_slice.get(slice_id, self._root_node)
        node = _ContextTreeNode(ctx, parent)
        self._context_slice[slice_id] = node
        return node
