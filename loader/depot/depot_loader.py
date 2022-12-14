import os

from UniTok import UniDep as OriUniDep

from loader.depot.depot_cache import DepotCache
from loader.global_setting import Setting
from utils.splitter import Splitter


class UniDep(OriUniDep):
    def __init__(self, store_dir):
        super().__init__(store_dir=store_dir)

    @classmethod
    def from_config(cls, store, sub_folder=None, filters=None):
        data_dir = store.data_dir
        if sub_folder:
            data_dir = os.path.join(data_dir, sub_folder)

        depot = cls(store_dir=data_dir)
        if store.union:
            depot.union(*[DepotCache.get(d) for d in store.union])

        if filters:
            for col in filters:
                for filtering in filters[col]:
                    if filtering == 'remove_empty':
                        filtering = 'x'
                    filterer = eval(f'lambda x: {filtering}')
                    print(f'filter for {col} ({filtering}): {depot.sample_size} -> ', end='')
                    depot.filter(filterer, col=col)
                    print(depot.sample_size)
        return depot

    @classmethod
    def parse(cls, data):
        depots = dict()
        splitter = None

        if data.has_split:
            for mode in data.split:
                filters = data.filters[mode]
                depots[mode] = cls.from_config(
                    store=data.store,
                    sub_folder=data.split[mode].path,
                    filters=filters,
                )
        else:
            filters = data.filters
            depot = cls.from_config(
                store=data.store,
                filters=filters
            )
            splitter = Splitter()
            for mode in data.split:
                assert mode in Setting.MODES

                splitter.add(
                    name=mode,
                    weight=data.split[mode].weight
                )
                depots[mode] = depot

        return depots, splitter
