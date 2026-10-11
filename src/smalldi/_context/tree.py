from smalldi.context import InjectionContext
from smalldi.concurrency import threadsafe


class _ContextTreeNode:
    def __init__(self, ctx: InjectionContext, parent: '_ContextTreeNode | None'):
        self.parent = parent
        self.context: InjectionContext = ctx


# Kinda reverse tree, nodes are parent aware, not child aware
class ContextTree:
    def __init__(self, root_context: InjectionContext):
        self.root = root_context
        self._root_node = _ContextTreeNode(root_context, None)
        self._context_slice: dict = dict()

    @threadsafe
    def get_current_node_for_id(self, slice_id) -> InjectionContext:
        return self._context_slice.get(slice_id, self._root_node).context

    @threadsafe
    def finish_context_for(self, slice_id):
        node = self._context_slice.get(slice_id)
        if node is None:
            raise ValueError(f"Context for slice id {slice_id} not found")
        if node.parent is self._root_node:
            del self._context_slice[slice_id]
        else:
            self._context_slice[slice_id] = node.parent

    @threadsafe
    def add_context_for(self, slice_id, ctx: InjectionContext):
        parent = self._context_slice.get(slice_id, self._root_node)
        self._context_slice[slice_id] = _ContextTreeNode(ctx, parent)