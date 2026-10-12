import unittest
import pandas as pd
from scripts.review_bollinger_filters import reentry


class ReentryTests(unittest.TestCase):
    def inputs(self):
        date=pd.Timestamp('2026-10-12T14:30Z')
        records=[{'close':100} for _ in range(20)]
        positions={date:19}
        closes={'2026-10-12':pd.Timestamp('2026-10-12T20:00Z')}
        event={'source_timestamp':'2026-10-12T14:33:00Z','side':'SUPERIOR'}
        return event,records,positions,closes

    def test_reentry_is_observed_in_first_next_minute(self):
        event,records,positions,closes=self.inputs()
        frame=pd.DataFrame({'close':[100]},index=pd.to_datetime(['2026-10-12T14:34Z']))
        self.assertTrue(reentry(event,frame,records,positions,closes,pd.Timestamp('2026-10-12T15:00Z')))

    def test_future_minute_cannot_be_used(self):
        event,records,positions,closes=self.inputs()
        frame=pd.DataFrame({'close':[100]},index=pd.to_datetime(['2026-10-12T14:34Z']))
        self.assertIsNone(reentry(event,frame,records,positions,closes,pd.Timestamp('2026-10-12T14:34Z')))

    def test_two_outside_closes_are_not_reentry(self):
        event,records,positions,closes=self.inputs()
        frame=pd.DataFrame({'close':[104,105]},index=pd.to_datetime(['2026-10-12T14:34Z','2026-10-12T14:35Z']))
        self.assertFalse(reentry(event,frame,records,positions,closes,pd.Timestamp('2026-10-12T15:00Z')))
