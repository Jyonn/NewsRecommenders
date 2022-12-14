class ColumnMap:
    def __init__(
            self,
            clicks_col: str = 'history',
            candidate_col: str = 'nid',
            label_col: str = 'click',
            neg_col: str = 'neg',
            group_col: str = 'imp',
    ):
        self.clicks_col = clicks_col
        self.candidate_col = candidate_col
        self.label_col = label_col
        self.neg_col = neg_col
        self.group_col = group_col
        self.clicks_mask_col = '__clicks_mask__'
