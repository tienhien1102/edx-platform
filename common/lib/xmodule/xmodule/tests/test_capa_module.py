# -*- coding: utf-8 -*-
"""
Tests of the Capa XModule
"""
# pylint: disable=C0111
# pylint: disable=R0904
# pylint: disable=C0103
# pylint: disable=C0302

import datetime
import json
import random
import os
import textwrap
import unittest

from mock import Mock, patch
import webob
from webob.multidict import MultiDict

import xmodule
from xmodule.tests import DATA_DIR
from capa.responsetypes import (StudentInputError, LoncapaProblemError,
                                ResponseError)
from capa.xqueue_interface import XQueueInterface
from xmodule.capa_module import CapaModule, ComplexEncoder
from opaque_keys.edx.locations import Location
from xblock.field_data import DictFieldData
from xblock.fields import ScopeIds

from . import get_test_system
from pytz import UTC
from capa.correctmap import CorrectMap


class CapaFactory(object):
    """
    A helper class to create problem modules with various parameters for testing.
    """

    sample_problem_xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <problem>
            <text>
                <p>What is pi, to two decimal places?</p>
            </text>
        <numericalresponse answer="3.14">
        <textline math="1" size="30"/>
        </numericalresponse>
        </problem>
    """)

    num = 0

    @classmethod
    def next_num(cls):
        cls.num += 1
        return cls.num

    @classmethod
    def input_key(cls, response_num=2, input_num=1):
        """
        Return the input key to use when passing GET parameters
        """
        return ("input_" + cls.answer_key(response_num, input_num))

    @classmethod
    def answer_key(cls, response_num=2, input_num=1):
        """
        Return the key stored in the capa problem answer dict
        """
        return (
            "%s_%d_%d" % (
                "-".join(['i4x', 'edX', 'capa_test', 'problem', 'SampleProblem%d' % cls.num]),
                response_num,
                input_num
            )
        )

    @classmethod
    def create(cls,
               attempts=None,
               problem_state=None,
               correct=False,
               xml=None,
               override_get_score=True,
               **kwargs
               ):
        """
        All parameters are optional, and are added to the created problem if specified.

        Arguments:
            graceperiod:
            due:
            max_attempts:
            showanswer:
            force_save_button:
            rerandomize: all strings, as specified in the policy for the problem

            problem_state: a dict to to be serialized into the instance_state of the
                module.

            attempts: also added to instance state.  Will be converted to an int.
        """
        location = Location(
            "edX",
            "capa_test",
            "2012_Fall",
            "problem",
            "SampleProblem{0}".format(cls.next_num()),
            None
        )
        if xml is None:
            xml = cls.sample_problem_xml
        field_data = {'data': xml}
        field_data.update(kwargs)
        descriptor = Mock(weight="1")
        if problem_state is not None:
            field_data.update(problem_state)
        if attempts is not None:
            # converting to int here because I keep putting "0" and "1" in the tests
            # since everything else is a string.
            field_data['attempts'] = int(attempts)

        system = get_test_system()
        system.render_template = Mock(return_value="<div>Test Template HTML</div>")
        module = CapaModule(
            descriptor,
            system,
            DictFieldData(field_data),
            ScopeIds(None, None, location, location),
        )

        if override_get_score:
            if correct:
                # TODO: probably better to actually set the internal state properly, but...
                module.get_score = lambda: {'score': 1, 'total': 1}
            else:
                module.get_score = lambda: {'score': 0, 'total': 1}

        return module


class CapaFactoryWithFiles(CapaFactory):
    """
    A factory for creating a Capa problem with files attached.
    """
    sample_problem_xml = textwrap.dedent("""\
        <problem>
            <coderesponse queuename="BerkeleyX-cs188x">
                <!-- actual filenames here don't matter for server-side tests,
                     they are only acted upon in the browser. -->
                <filesubmission
                    points="25"
                    allowed_files="prog1.py prog2.py prog3.py"
                    required_files="prog1.py prog2.py prog3.py"
                />
                <codeparam>
                    <answer_display>
                        If you're having trouble with this Project,
                        please refer to the Lecture Slides and attend office hours.
                    </answer_display>
                    <grader_payload>{"project": "p3"}</grader_payload>
                </codeparam>
            </coderesponse>

            <customresponse>
                <text>
                    If you worked with a partner, enter their username or email address. If you
                    worked alone, enter None.
                </text>

                <textline points="0" size="40" correct_answer="Your partner's username or 'None'"/>
                <answer type="loncapa/python">
correct=['correct']
s = str(submission[0]).strip()
if submission[0] == '':
    correct[0] = 'incorrect'
                </answer>
            </customresponse>
        </problem>
    """)


class CapaModuleTest(unittest.TestCase):

    def setUp(self):
        now = datetime.datetime.now(UTC)
        day_delta = datetime.timedelta(days=1)
        self.yesterday_str = str(now - day_delta)
        self.today_str = str(now)
        self.tomorrow_str = str(now + day_delta)

        # in the capa grace period format, not in time delta format
        self.two_day_delta_str = "2 days"

    def test_import(self):
        module = CapaFactory.create()
        self.assertEqual(module.get_score()['score'], 0)

        other_module = CapaFactory.create()
        self.assertEqual(module.get_score()['score'], 0)
        self.assertNotEqual(module.url_name, other_module.url_name,
                            "Factory should be creating unique names for each problem")

    def test_correct(self):
        """
        Check that the factory creates correct and incorrect problems properly.
        """
        module = CapaFactory.create()
        self.assertEqual(module.get_score()['score'], 0)

        other_module = CapaFactory.create(correct=True)
        self.assertEqual(other_module.get_score()['score'], 1)

    def test_get_score(self):
        """
        Do 1 test where the internals of get_score are properly set

        @jbau Note: this obviously depends on a particular implementation of get_score, but I think this is actually
        useful as unit-code coverage for this current implementation.  I don't see a layer where LoncapaProblem
        is tested directly
        """
        from capa.correctmap import CorrectMap
        student_answers = {'1_2_1': 'abcd'}
        correct_map = CorrectMap(answer_id='1_2_1', correctness="correct", npoints=0.9)
        module = CapaFactory.create(correct=True, override_get_score=False)
        module.lcp.correct_map = correct_map
        module.lcp.student_answers = student_answers
        self.assertEqual(module.get_score()['score'], 0.9)

        other_correct_map = CorrectMap(answer_id='1_2_1', correctness="incorrect", npoints=0.1)
        other_module = CapaFactory.create(correct=False, override_get_score=False)
        other_module.lcp.correct_map = other_correct_map
        other_module.lcp.student_answers = student_answers
        self.assertEqual(other_module.get_score()['score'], 0.1)

    def test_showanswer_default(self):
        """
        Make sure the show answer logic does the right thing.
        """
        # default, no due date, showanswer 'closed', so problem is open, and show_answer
        # not visible.
        problem = CapaFactory.create()
        self.assertFalse(problem.answer_available())

    def test_showanswer_attempted(self):
        problem = CapaFactory.create(showanswer='attempted')
        self.assertFalse(problem.answer_available())
        problem.attempts = 1
        self.assertTrue(problem.answer_available())

    def test_showanswer_closed(self):

        # can see after attempts used up, even with due date in the future
        used_all_attempts = CapaFactory.create(showanswer='closed',
                                               max_attempts="1",
                                               attempts="1",
                                               due=self.tomorrow_str)
        self.assertTrue(used_all_attempts.answer_available())

        # can see after due date
        after_due_date = CapaFactory.create(showanswer='closed',
                                            max_attempts="1",
                                            attempts="0",
                                            due=self.yesterday_str)

        self.assertTrue(after_due_date.answer_available())

        # can't see because attempts left
        attempts_left_open = CapaFactory.create(showanswer='closed',
                                                max_attempts="1",
                                                attempts="0",
                                                due=self.tomorrow_str)
        self.assertFalse(attempts_left_open.answer_available())

        # Can't see because grace period hasn't expired
        still_in_grace = CapaFactory.create(showanswer='closed',
                                            max_attempts="1",
                                            attempts="0",
                                            due=self.yesterday_str,
                                            graceperiod=self.two_day_delta_str)
        self.assertFalse(still_in_grace.answer_available())

    def test_showanswer_correct_or_past_due(self):
        """
        With showanswer="correct_or_past_due" should show answer after the answer is correct
        or after the problem is closed for everyone--e.g. after due date + grace period.
        """

        # can see because answer is correct, even with due date in the future
        answer_correct = CapaFactory.create(showanswer='correct_or_past_due',
                                            max_attempts="1",
                                            attempts="0",
                                            due=self.tomorrow_str,
                                            correct=True)
        self.assertTrue(answer_correct.answer_available())

        # can see after due date, even when answer isn't correct
        past_due_date = CapaFactory.create(showanswer='correct_or_past_due',
                                           max_attempts="1",
                                           attempts="0",
                                           due=self.yesterday_str)
        self.assertTrue(past_due_date.answer_available())

        # can also see after due date when answer _is_ correct
        past_due_date_correct = CapaFactory.create(showanswer='correct_or_past_due',
                                                   max_attempts="1",
                                                   attempts="0",
                                                   due=self.yesterday_str,
                                                   correct=True)
        self.assertTrue(past_due_date_correct.answer_available())

        # Can't see because grace period hasn't expired and answer isn't correct
        still_in_grace = CapaFactory.create(showanswer='correct_or_past_due',
                                            max_attempts="1",
                                            attempts="1",
                                            due=self.yesterday_str,
                                            graceperiod=self.two_day_delta_str)
        self.assertFalse(still_in_grace.answer_available())

    def test_showanswer_past_due(self):
        """
        With showanswer="past_due" should only show answer after the problem is closed
        for everyone--e.g. after due date + grace period.
        """

        # can't see after attempts used up, even with due date in the future
        used_all_attempts = CapaFactory.create(showanswer='past_due',
                                               max_attempts="1",
                                               attempts="1",
                                               due=self.tomorrow_str)
        self.assertFalse(used_all_attempts.answer_available())

        # can see after due date
        past_due_date = CapaFactory.create(showanswer='past_due',
                                           max_attempts="1",
                                           attempts="0",
                                           due=self.yesterday_str)
        self.assertTrue(past_due_date.answer_available())

        # can't see because attempts left
        attempts_left_open = CapaFactory.create(showanswer='past_due',
                                                max_attempts="1",
                                                attempts="0",
                                                due=self.tomorrow_str)
        self.assertFalse(attempts_left_open.answer_available())

        # Can't see because grace period hasn't expired, even though have no more
        # attempts.
        still_in_grace = CapaFactory.create(showanswer='past_due',
                                            max_attempts="1",
                                            attempts="1",
                                            due=self.yesterday_str,
                                            graceperiod=self.two_day_delta_str)
        self.assertFalse(still_in_grace.answer_available())

    def test_showanswer_finished(self):
        """
        With showanswer="finished" should show answer after the problem is closed,
        or after the answer is correct.
        """

        # can see after attempts used up, even with due date in the future
        used_all_attempts = CapaFactory.create(showanswer='finished',
                                               max_attempts="1",
                                               attempts="1",
                                               due=self.tomorrow_str)
        self.assertTrue(used_all_attempts.answer_available())

        # can see after due date
        past_due_date = CapaFactory.create(showanswer='finished',
                                           max_attempts="1",
                                           attempts="0",
                                           due=self.yesterday_str)
        self.assertTrue(past_due_date.answer_available())

        # can't see because attempts left and wrong
        attempts_left_open = CapaFactory.create(showanswer='finished',
                                                max_attempts="1",
                                                attempts="0",
                                                due=self.tomorrow_str)
        self.assertFalse(attempts_left_open.answer_available())

        # _can_ see because attempts left and right
        correct_ans = CapaFactory.create(showanswer='finished',
                                         max_attempts="1",
                                         attempts="0",
                                         due=self.tomorrow_str,
                                         correct=True)
        self.assertTrue(correct_ans.answer_available())

        # Can see even though grace period hasn't expired, because have no more
        # attempts.
        still_in_grace = CapaFactory.create(showanswer='finished',
                                            max_attempts="1",
                                            attempts="1",
                                            due=self.yesterday_str,
                                            graceperiod=self.two_day_delta_str)
        self.assertTrue(still_in_grace.answer_available())

    def test_closed(self):

        # Attempts < Max attempts --> NOT closed
        module = CapaFactory.create(max_attempts="1", attempts="0")
        self.assertFalse(module.closed())

        # Attempts < Max attempts --> NOT closed
        module = CapaFactory.create(max_attempts="2", attempts="1")
        self.assertFalse(module.closed())

        # Attempts = Max attempts --> closed
        module = CapaFactory.create(max_attempts="1", attempts="1")
        self.assertTrue(module.closed())

        # Attempts > Max attempts --> closed
        module = CapaFactory.create(max_attempts="1", attempts="2")
        self.assertTrue(module.closed())

        # Max attempts = 0 --> closed
        module = CapaFactory.create(max_attempts="0", attempts="2")
        self.assertTrue(module.closed())

        # Past due --> closed
        module = CapaFactory.create(max_attempts="1", attempts="0",
                                    due=self.yesterday_str)
        self.assertTrue(module.closed())

    def test_due_date_extension(self):

        module = CapaFactory.create(
            max_attempts="1", attempts="0", due=self.yesterday_str,
            extended_due=self.tomorrow_str)
        self.assertFalse(module.closed())

    def test_parse_get_params(self):

        # Valid GET param dict
        # 'input_5' intentionally left unset,
        valid_get_dict = MultiDict({
            'input_1': 'test',
            'input_1_2': 'test',
            'input_1_2_3': 'test',
            'input_[]_3': 'test',
            'input_4': None,
            'input_6': 5
        })

        result = CapaModule.make_dict_of_responses(valid_get_dict)

        # Expect that we get a dict with "input" stripped from key names
        # and that we get the same values back
        for key in result.keys():
            original_key = "input_" + key
            self.assertTrue(original_key in valid_get_dict,
                            "Output dict should have key %s" % original_key)
            self.assertEqual(valid_get_dict[original_key], result[key])

        # Valid GET param dict with list keys
        # Each tuple represents a single parameter in the query string
        valid_get_dict = MultiDict((('input_2[]', 'test1'), ('input_2[]', 'test2')))
        result = CapaModule.make_dict_of_responses(valid_get_dict)
        self.assertTrue('2' in result)
        self.assertEqual(['test1', 'test2'], result['2'])

        # If we use [] at the end of a key name, we should always
        # get a list, even if there's just one value
        valid_get_dict = MultiDict({'input_1[]': 'test'})
        result = CapaModule.make_dict_of_responses(valid_get_dict)
        self.assertEqual(result['1'], ['test'])

        # If we have no underscores in the name, then the key is invalid
        invalid_get_dict = MultiDict({'input': 'test'})
        with self.assertRaises(ValueError):
            result = CapaModule.make_dict_of_responses(invalid_get_dict)

        # Two equivalent names (one list, one non-list)
        # One of the values would overwrite the other, so detect this
        # and raise an exception
        invalid_get_dict = MultiDict({'input_1[]': 'test 1',
                                      'input_1': 'test 2'})
        with self.assertRaises(ValueError):
            result = CapaModule.make_dict_of_responses(invalid_get_dict)

    def test_check_problem_correct(self):

        module = CapaFactory.create(attempts=1)

        # Simulate that all answers are marked correct, no matter
        # what the input is, by patching CorrectMap.is_correct()
        # Also simulate rendering the HTML
        # TODO: pep8 thinks the following line has invalid syntax
        with patch('capa.correctmap.CorrectMap.is_correct') as mock_is_correct, \
                patch('xmodule.capa_module.CapaModule.get_problem_html') as mock_html:
            mock_is_correct.return_value = True
            mock_html.return_value = "Test HTML"

            # Check the problem
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.check_problem(get_request_dict)

        # Expect that the problem is marked correct
        self.assertEqual(result['success'], 'correct')

        # Expect that we get the (mocked) HTML
        self.assertEqual(result['contents'], 'Test HTML')

        # Expect that the number of attempts is incremented by 1
        self.assertEqual(module.attempts, 2)

    def test_check_problem_incorrect(self):

        module = CapaFactory.create(attempts=0)

        # Simulate marking the input incorrect
        with patch('capa.correctmap.CorrectMap.is_correct') as mock_is_correct:
            mock_is_correct.return_value = False

            # Check the problem
            get_request_dict = {CapaFactory.input_key(): '0'}
            result = module.check_problem(get_request_dict)

        # Expect that the problem is marked correct
        self.assertEqual(result['success'], 'incorrect')

        # Expect that the number of attempts is incremented by 1
        self.assertEqual(module.attempts, 1)

    def test_check_problem_closed(self):
        module = CapaFactory.create(attempts=3)

        # Problem closed -- cannot submit
        # Simulate that CapaModule.closed() always returns True
        with patch('xmodule.capa_module.CapaModule.closed') as mock_closed:
            mock_closed.return_value = True
            with self.assertRaises(xmodule.exceptions.NotFoundError):
                get_request_dict = {CapaFactory.input_key(): '3.14'}
                module.check_problem(get_request_dict)

        # Expect that number of attempts NOT incremented
        self.assertEqual(module.attempts, 3)

    def test_check_problem_resubmitted_with_randomize(self):
        rerandomize_values = ['always', 'true']

        for rerandomize in rerandomize_values:
            # Randomize turned on
            module = CapaFactory.create(rerandomize=rerandomize, attempts=0)

            # Simulate that the problem is completed
            module.done = True

            # Expect that we cannot submit
            with self.assertRaises(xmodule.exceptions.NotFoundError):
                get_request_dict = {CapaFactory.input_key(): '3.14'}
                module.check_problem(get_request_dict)

            # Expect that number of attempts NOT incremented
            self.assertEqual(module.attempts, 0)

    def test_check_problem_resubmitted_no_randomize(self):
        rerandomize_values = ['never', 'false', 'per_student']

        for rerandomize in rerandomize_values:
            # Randomize turned off
            module = CapaFactory.create(rerandomize=rerandomize, attempts=0, done=True)

            # Expect that we can submit successfully
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.check_problem(get_request_dict)

            self.assertEqual(result['success'], 'correct')

            # Expect that number of attempts IS incremented
            self.assertEqual(module.attempts, 1)

    def test_check_problem_queued(self):
        module = CapaFactory.create(attempts=1)

        # Simulate that the problem is queued
        with patch('capa.capa_problem.LoncapaProblem.is_queued') \
                as mock_is_queued, \
            patch('capa.capa_problem.LoncapaProblem.get_recentmost_queuetime') \
                as mock_get_queuetime:

            mock_is_queued.return_value = True
            mock_get_queuetime.return_value = datetime.datetime.now(UTC)

            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.check_problem(get_request_dict)

            # Expect an AJAX alert message in 'success'
            self.assertTrue('You must wait' in result['success'])

        # Expect that the number of attempts is NOT incremented
        self.assertEqual(module.attempts, 1)

    def test_check_problem_with_files(self):
        # Check a problem with uploaded files, using the check_problem API.
        # pylint: disable=W0212

        # The files we'll be uploading.
        fnames = ["prog1.py", "prog2.py", "prog3.py"]
        fpaths = [os.path.join(DATA_DIR, "capa", fname) for fname in fnames]
        fileobjs = [open(fpath) for fpath in fpaths]
        for fileobj in fileobjs:
            self.addCleanup(fileobj.close)

        module = CapaFactoryWithFiles.create()

        # Mock the XQueueInterface.
        xqueue_interface = XQueueInterface("http://example.com/xqueue", Mock())
        xqueue_interface._http_post = Mock(return_value=(0, "ok"))
        module.system.xqueue['interface'] = xqueue_interface

        # Create a request dictionary for check_problem.
        get_request_dict = {
            CapaFactoryWithFiles.input_key(response_num=2): fileobjs,
            CapaFactoryWithFiles.input_key(response_num=3): 'None',
        }

        module.check_problem(get_request_dict)

        # _http_post is called like this:
        #   _http_post(
        #       'http://example.com/xqueue/xqueue/submit/',
        #       {
        #           'xqueue_header': '{"lms_key": "df34fb702620d7ae892866ba57572491", "lms_callback_url": "/", "queue_name": "BerkeleyX-cs188x"}',
        #           'xqueue_body': '{"student_info": "{\\"anonymous_student_id\\": \\"student\\", \\"submission_time\\": \\"20131117183318\\"}", "grader_payload": "{\\"project\\": \\"p3\\"}", "student_response": ""}',
        #       },
        #       files={
        #           path(u'/home/ned/edx/edx-platform/common/test/data/uploads/asset.html'):
        #               <open file u'/home/ned/edx/edx-platform/common/test/data/uploads/asset.html', mode 'r' at 0x49c5f60>,
        #           path(u'/home/ned/edx/edx-platform/common/test/data/uploads/image.jpg'):
        #               <open file u'/home/ned/edx/edx-platform/common/test/data/uploads/image.jpg', mode 'r' at 0x49c56f0>,
        #           path(u'/home/ned/edx/edx-platform/common/test/data/uploads/textbook.pdf'):
        #               <open file u'/home/ned/edx/edx-platform/common/test/data/uploads/textbook.pdf', mode 'r' at 0x49c5a50>,
        #       },
        #   )

        self.assertEqual(xqueue_interface._http_post.call_count, 1)
        _, kwargs = xqueue_interface._http_post.call_args
        self.assertItemsEqual(fpaths, kwargs['files'].keys())
        for fpath, fileobj in kwargs['files'].iteritems():
            self.assertEqual(fpath, fileobj.name)

    def test_check_problem_with_files_as_xblock(self):
        # Check a problem with uploaded files, using the XBlock API.
        # pylint: disable=W0212

        # The files we'll be uploading.
        fnames = ["prog1.py", "prog2.py", "prog3.py"]
        fpaths = [os.path.join(DATA_DIR, "capa", fname) for fname in fnames]
        fileobjs = [open(fpath) for fpath in fpaths]
        for fileobj in fileobjs:
            self.addCleanup(fileobj.close)

        module = CapaFactoryWithFiles.create()

        # Mock the XQueueInterface.
        xqueue_interface = XQueueInterface("http://example.com/xqueue", Mock())
        xqueue_interface._http_post = Mock(return_value=(0, "ok"))
        module.system.xqueue['interface'] = xqueue_interface

        # Create a webob Request with the files uploaded.
        post_data = []
        for fname, fileobj in zip(fnames, fileobjs):
            post_data.append((CapaFactoryWithFiles.input_key(response_num=2), (fname, fileobj)))
        post_data.append((CapaFactoryWithFiles.input_key(response_num=3), 'None'))
        request = webob.Request.blank("/some/fake/url", POST=post_data, content_type='multipart/form-data')

        module.handle('xmodule_handler', request, 'problem_check')

        self.assertEqual(xqueue_interface._http_post.call_count, 1)
        _, kwargs = xqueue_interface._http_post.call_args
        self.assertItemsEqual(fnames, kwargs['files'].keys())
        for fpath, fileobj in kwargs['files'].iteritems():
            self.assertEqual(fpath, fileobj.name)

    def test_check_problem_error(self):

        # Try each exception that capa_module should handle
        exception_classes = [StudentInputError,
                             LoncapaProblemError,
                             ResponseError]
        for exception_class in exception_classes:

            # Create the module
            module = CapaFactory.create(attempts=1)

            # Ensure that the user is NOT staff
            module.system.user_is_staff = False

            # Simulate answering a problem that raises the exception
            with patch('capa.capa_problem.LoncapaProblem.grade_answers') as mock_grade:
                mock_grade.side_effect = exception_class('test error')

                get_request_dict = {CapaFactory.input_key(): '3.14'}
                result = module.check_problem(get_request_dict)

            # Expect an AJAX alert message in 'success'
            expected_msg = 'Error: test error'
            self.assertEqual(expected_msg, result['success'])

            # Expect that the number of attempts is NOT incremented
            self.assertEqual(module.attempts, 1)

    def test_check_problem_other_errors(self):
        """
        Test that errors other than the expected kinds give an appropriate message.

        See also `test_check_problem_error` for the "expected kinds" or errors.
        """
        # Create the module
        module = CapaFactory.create(attempts=1)

        # Ensure that the user is NOT staff
        module.system.user_is_staff = False

        # Ensure that DEBUG is on
        module.system.DEBUG = True

        # Simulate answering a problem that raises the exception
        with patch('capa.capa_problem.LoncapaProblem.grade_answers') as mock_grade:
            error_msg = u"Superterrible error happened: ☠"
            mock_grade.side_effect = Exception(error_msg)

            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.check_problem(get_request_dict)

        # Expect an AJAX alert message in 'success'
        self.assertTrue(error_msg in result['success'])

    def test_check_problem_error_nonascii(self):

        # Try each exception that capa_module should handle
        exception_classes = [StudentInputError,
                             LoncapaProblemError,
                             ResponseError]
        for exception_class in exception_classes:

            # Create the module
            module = CapaFactory.create(attempts=1)

            # Ensure that the user is NOT staff
            module.system.user_is_staff = False

            # Simulate answering a problem that raises the exception
            with patch('capa.capa_problem.LoncapaProblem.grade_answers') as mock_grade:
                mock_grade.side_effect = exception_class(u"ȧƈƈḗƞŧḗḓ ŧḗẋŧ ƒǿř ŧḗşŧīƞɠ")

                get_request_dict = {CapaFactory.input_key(): '3.14'}
                result = module.check_problem(get_request_dict)

            # Expect an AJAX alert message in 'success'
            expected_msg = u'Error: ȧƈƈḗƞŧḗḓ ŧḗẋŧ ƒǿř ŧḗşŧīƞɠ'
            self.assertEqual(expected_msg, result['success'])

            # Expect that the number of attempts is NOT incremented
            self.assertEqual(module.attempts, 1)

    def test_check_problem_error_with_staff_user(self):

        # Try each exception that capa module should handle
        for exception_class in [StudentInputError,
                                LoncapaProblemError,
                                ResponseError]:

            # Create the module
            module = CapaFactory.create(attempts=1)

            # Ensure that the user IS staff
            module.system.user_is_staff = True

            # Simulate answering a problem that raises an exception
            with patch('capa.capa_problem.LoncapaProblem.grade_answers') as mock_grade:
                mock_grade.side_effect = exception_class('test error')

                get_request_dict = {CapaFactory.input_key(): '3.14'}
                result = module.check_problem(get_request_dict)

            # Expect an AJAX alert message in 'success'
            self.assertTrue('test error' in result['success'])

            # We DO include traceback information for staff users
            self.assertTrue('Traceback' in result['success'])

            # Expect that the number of attempts is NOT incremented
            self.assertEqual(module.attempts, 1)

    def test_reset_problem(self):
        module = CapaFactory.create(done=True)
        module.new_lcp = Mock(wraps=module.new_lcp)
        module.choose_new_seed = Mock(wraps=module.choose_new_seed)

        # Stub out HTML rendering
        with patch('xmodule.capa_module.CapaModule.get_problem_html') as mock_html:
            mock_html.return_value = "<div>Test HTML</div>"

            # Reset the problem
            get_request_dict = {}
            result = module.reset_problem(get_request_dict)

        # Expect that the request was successful
        self.assertTrue('success' in result and result['success'])

        # Expect that the problem HTML is retrieved
        self.assertTrue('html' in result)
        self.assertEqual(result['html'], "<div>Test HTML</div>")

        # Expect that the problem was reset
        module.new_lcp.assert_called_once_with(None)

    def test_reset_problem_closed(self):
        # pre studio default
        module = CapaFactory.create(rerandomize="always")

        # Simulate that the problem is closed
        with patch('xmodule.capa_module.CapaModule.closed') as mock_closed:
            mock_closed.return_value = True

            # Try to reset the problem
            get_request_dict = {}
            result = module.reset_problem(get_request_dict)

        # Expect that the problem was NOT reset
        self.assertTrue('success' in result and not result['success'])

    def test_reset_problem_not_done(self):
        # Simulate that the problem is NOT done
        module = CapaFactory.create(done=False)

        # Try to reset the problem
        get_request_dict = {}
        result = module.reset_problem(get_request_dict)

        # Expect that the problem was NOT reset
        self.assertTrue('success' in result and not result['success'])

    def test_rescore_problem_correct(self):

        module = CapaFactory.create(attempts=1, done=True)

        # Simulate that all answers are marked correct, no matter
        # what the input is, by patching LoncapaResponse.evaluate_answers()
        with patch('capa.responsetypes.LoncapaResponse.evaluate_answers') as mock_evaluate_answers:
            mock_evaluate_answers.return_value = CorrectMap(CapaFactory.answer_key(), 'correct')
            result = module.rescore_problem()

        # Expect that the problem is marked correct
        self.assertEqual(result['success'], 'correct')

        # Expect that we get no HTML
        self.assertFalse('contents' in result)

        # Expect that the number of attempts is not incremented
        self.assertEqual(module.attempts, 1)

    def test_rescore_problem_incorrect(self):
        # make sure it also works when attempts have been reset,
        # so add this to the test:
        module = CapaFactory.create(attempts=0, done=True)

        # Simulate that all answers are marked incorrect, no matter
        # what the input is, by patching LoncapaResponse.evaluate_answers()
        with patch('capa.responsetypes.LoncapaResponse.evaluate_answers') as mock_evaluate_answers:
            mock_evaluate_answers.return_value = CorrectMap(CapaFactory.answer_key(), 'incorrect')
            result = module.rescore_problem()

        # Expect that the problem is marked incorrect
        self.assertEqual(result['success'], 'incorrect')

        # Expect that the number of attempts is not incremented
        self.assertEqual(module.attempts, 0)

    def test_rescore_problem_not_done(self):
        # Simulate that the problem is NOT done
        module = CapaFactory.create(done=False)

        # Try to rescore the problem, and get exception
        with self.assertRaises(xmodule.exceptions.NotFoundError):
            module.rescore_problem()

    def test_rescore_problem_not_supported(self):
        module = CapaFactory.create(done=True)

        # Try to rescore the problem, and get exception
        with patch('capa.capa_problem.LoncapaProblem.supports_rescoring') as mock_supports_rescoring:
            mock_supports_rescoring.return_value = False
            with self.assertRaises(NotImplementedError):
                module.rescore_problem()

    def _rescore_problem_error_helper(self, exception_class):
        """Helper to allow testing all errors that rescoring might return."""
        # Create the module
        module = CapaFactory.create(attempts=1, done=True)

        # Simulate answering a problem that raises the exception
        with patch('capa.capa_problem.LoncapaProblem.rescore_existing_answers') as mock_rescore:
            mock_rescore.side_effect = exception_class(u'test error \u03a9')
            result = module.rescore_problem()

        # Expect an AJAX alert message in 'success'
        expected_msg = u'Error: test error \u03a9'
        self.assertEqual(result['success'], expected_msg)

        # Expect that the number of attempts is NOT incremented
        self.assertEqual(module.attempts, 1)

    def test_rescore_problem_student_input_error(self):
        self._rescore_problem_error_helper(StudentInputError)

    def test_rescore_problem_problem_error(self):
        self._rescore_problem_error_helper(LoncapaProblemError)

    def test_rescore_problem_response_error(self):
        self._rescore_problem_error_helper(ResponseError)

    def test_save_problem(self):
        module = CapaFactory.create(done=False)

        # Save the problem
        get_request_dict = {CapaFactory.input_key(): '3.14'}
        result = module.save_problem(get_request_dict)

        # Expect that answers are saved to the problem
        expected_answers = {CapaFactory.answer_key(): '3.14'}
        self.assertEqual(module.lcp.student_answers, expected_answers)

        # Expect that the result is success
        self.assertTrue('success' in result and result['success'])

    def test_save_problem_closed(self):
        module = CapaFactory.create(done=False)

        # Simulate that the problem is closed
        with patch('xmodule.capa_module.CapaModule.closed') as mock_closed:
            mock_closed.return_value = True

            # Try to save the problem
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.save_problem(get_request_dict)

        # Expect that the result is failure
        self.assertTrue('success' in result and not result['success'])

    def test_save_problem_submitted_with_randomize(self):

        # Capa XModule treats 'always' and 'true' equivalently
        rerandomize_values = ['always', 'true']

        for rerandomize in rerandomize_values:
            module = CapaFactory.create(rerandomize=rerandomize, done=True)

            # Try to save
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.save_problem(get_request_dict)

            # Expect that we cannot save
            self.assertTrue('success' in result and not result['success'])

    def test_save_problem_submitted_no_randomize(self):

        # Capa XModule treats 'false' and 'per_student' equivalently
        rerandomize_values = ['never', 'false', 'per_student']

        for rerandomize in rerandomize_values:
            module = CapaFactory.create(rerandomize=rerandomize, done=True)

            # Try to save
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            result = module.save_problem(get_request_dict)

            # Expect that we succeed
            self.assertTrue('success' in result and result['success'])

    def test_check_button_name(self):

        # If last attempt, button name changes to "Submit"
        # Just in case, we also check what happens if we have
        # more attempts than allowed.
        attempts = random.randint(1, 10)
        module = CapaFactory.create(attempts=attempts - 1, max_attempts=attempts)
        self.assertEqual(module.check_button_name(), "Final Submit")

        module = CapaFactory.create(attempts=attempts, max_attempts=attempts)
        self.assertEqual(module.check_button_name(), "Final Submit")

        module = CapaFactory.create(attempts=attempts + 1, max_attempts=attempts)
        self.assertEqual(module.check_button_name(), "Final Submit")

        module = CapaFactory.create(attempts=attempts - 2, max_attempts=attempts)
        self.assertEqual(module.check_button_name(), "Submit")

        module = CapaFactory.create(attempts=attempts - 3, max_attempts=attempts)
        self.assertEqual(module.check_button_name(), "Submit")

        # If no limit on attempts
        module = CapaFactory.create(attempts=attempts - 3)
        self.assertEqual(module.check_button_name(), "Submit")

        module = CapaFactory.create(attempts=0)
        self.assertEqual(module.check_button_name(), "Submit")

    def test_check_button_checking_name(self):
        module = CapaFactory.create(attempts=1, max_attempts=10)
        self.assertEqual(module.check_button_checking_name(), "Checking...")

        module = CapaFactory.create(attempts=10, max_attempts=10)
        self.assertEqual(module.check_button_checking_name(), "Checking...")

    def test_check_button_name_customization(self):
        module = CapaFactory.create(
            attempts=1,
            max_attempts=10,
            text_customization={"custom_check": "Submit", "custom_final_check": "Final Submit"}
        )
        self.assertEqual(module.check_button_name(), "Submit")

        module = CapaFactory.create(attempts=9,
                                    max_attempts=10,
                                    text_customization={"custom_check": "Submit", "custom_final_check": "Final Submit"}
                                    )
        self.assertEqual(module.check_button_name(), "Final Submit")

    def test_check_button_checking_name_customization(self):
        module = CapaFactory.create(
            attempts=1,
            max_attempts=10,
            text_customization={
                "custom_check": "Submit",
                "custom_final_check": "Final Submit",
                "custom_checking": "Checking..."
            }
        )
        self.assertEqual(module.check_button_checking_name(), "Checking...")

        module = CapaFactory.create(
            attempts=9,
            max_attempts=10,
            text_customization={
                "custom_check": "Submit",
                "custom_final_check": "Final Submit",
                "custom_checking": "Checking..."
            }
        )
        self.assertEqual(module.check_button_checking_name(), "Checking...")

    def test_should_show_check_button(self):

        attempts = random.randint(1, 10)

        # If we're after the deadline, do NOT show check button
        module = CapaFactory.create(due=self.yesterday_str)
        self.assertFalse(module.should_show_check_button())

        # If user is out of attempts, do NOT show the check button
        module = CapaFactory.create(attempts=attempts, max_attempts=attempts)
        self.assertFalse(module.should_show_check_button())

        # If survey question (max_attempts = 0), do NOT show the check button
        module = CapaFactory.create(max_attempts=0)
        self.assertFalse(module.should_show_check_button())

        # If user submitted a problem but hasn't reset,
        # do NOT show the check button
        # Note:  we can only reset when rerandomize="always" or "true"
        module = CapaFactory.create(rerandomize="always", done=True)
        self.assertFalse(module.should_show_check_button())

        module = CapaFactory.create(rerandomize="true", done=True)
        self.assertFalse(module.should_show_check_button())

        # Otherwise, DO show the check button
        module = CapaFactory.create()
        self.assertTrue(module.should_show_check_button())

        # If the user has submitted the problem
        # and we do NOT have a reset button, then we can show the check button
        # Setting rerandomize to "never" or "false" ensures that the reset button
        # is not shown
        module = CapaFactory.create(rerandomize="never", done=True)
        self.assertTrue(module.should_show_check_button())

        module = CapaFactory.create(rerandomize="false", done=True)
        self.assertTrue(module.should_show_check_button())

        module = CapaFactory.create(rerandomize="per_student", done=True)
        self.assertTrue(module.should_show_check_button())

    def test_should_show_reset_button(self):

        attempts = random.randint(1, 10)

        # If we're after the deadline, do NOT show the reset button
        module = CapaFactory.create(due=self.yesterday_str, done=True)
        self.assertFalse(module.should_show_reset_button())

        # If the user is out of attempts, do NOT show the reset button
        module = CapaFactory.create(attempts=attempts, max_attempts=attempts, done=True)
        self.assertFalse(module.should_show_reset_button())

        # If we're NOT randomizing, then do NOT show the reset button
        module = CapaFactory.create(rerandomize="never", done=True)
        self.assertFalse(module.should_show_reset_button())

        # If we're NOT randomizing, then do NOT show the reset button
        module = CapaFactory.create(rerandomize="per_student", done=True)
        self.assertFalse(module.should_show_reset_button())

        # If we're NOT randomizing, then do NOT show the reset button
        module = CapaFactory.create(rerandomize="false", done=True)
        self.assertFalse(module.should_show_reset_button())

        # If the user hasn't submitted an answer yet,
        # then do NOT show the reset button
        module = CapaFactory.create(done=False)
        self.assertFalse(module.should_show_reset_button())

        # pre studio default value, DO show the reset button
        module = CapaFactory.create(rerandomize="always", done=True)
        self.assertTrue(module.should_show_reset_button())

        # If survey question for capa (max_attempts = 0),
        # DO show the reset button
        module = CapaFactory.create(rerandomize="always", max_attempts=0, done=True)
        self.assertTrue(module.should_show_reset_button())

    def test_should_show_save_button(self):

        attempts = random.randint(1, 10)

        # If we're after the deadline, do NOT show the save button
        module = CapaFactory.create(due=self.yesterday_str, done=True)
        self.assertFalse(module.should_show_save_button())

        # If the user is out of attempts, do NOT show the save button
        module = CapaFactory.create(attempts=attempts, max_attempts=attempts, done=True)
        self.assertFalse(module.should_show_save_button())

        # If user submitted a problem but hasn't reset, do NOT show the save button
        module = CapaFactory.create(rerandomize="always", done=True)
        self.assertFalse(module.should_show_save_button())

        module = CapaFactory.create(rerandomize="true", done=True)
        self.assertFalse(module.should_show_save_button())

        # If the user has unlimited attempts and we are not randomizing,
        # then do NOT show a save button
        # because they can keep using "Check"
        module = CapaFactory.create(max_attempts=None, rerandomize="never", done=False)
        self.assertFalse(module.should_show_save_button())

        module = CapaFactory.create(max_attempts=None, rerandomize="false", done=True)
        self.assertFalse(module.should_show_save_button())

        module = CapaFactory.create(max_attempts=None, rerandomize="per_student", done=True)
        self.assertFalse(module.should_show_save_button())

        # pre-studio default, DO show the save button
        module = CapaFactory.create(rerandomize="always", done=False)
        self.assertTrue(module.should_show_save_button())

        # If we're not randomizing and we have limited attempts,  then we can save
        module = CapaFactory.create(rerandomize="never", max_attempts=2, done=True)
        self.assertTrue(module.should_show_save_button())

        module = CapaFactory.create(rerandomize="false", max_attempts=2, done=True)
        self.assertTrue(module.should_show_save_button())

        module = CapaFactory.create(rerandomize="per_student", max_attempts=2, done=True)
        self.assertTrue(module.should_show_save_button())

        # If survey question for capa (max_attempts = 0),
        # DO show the save button
        module = CapaFactory.create(max_attempts=0, done=False)
        self.assertTrue(module.should_show_save_button())

    def test_should_show_save_button_force_save_button(self):
        # If we're after the deadline, do NOT show the save button
        # even though we're forcing a save
        module = CapaFactory.create(due=self.yesterday_str,
                                    force_save_button="true",
                                    done=True)
        self.assertFalse(module.should_show_save_button())

        # If the user is out of attempts, do NOT show the save button
        attempts = random.randint(1, 10)
        module = CapaFactory.create(attempts=attempts,
                                    max_attempts=attempts,
                                    force_save_button="true",
                                    done=True)
        self.assertFalse(module.should_show_save_button())

        # Otherwise, if we force the save button,
        # then show it even if we would ordinarily
        # require a reset first
        module = CapaFactory.create(force_save_button="true",
                                    rerandomize="always",
                                    done=True)
        self.assertTrue(module.should_show_save_button())

        module = CapaFactory.create(force_save_button="true",
                                    rerandomize="true",
                                    done=True)
        self.assertTrue(module.should_show_save_button())

    def test_no_max_attempts(self):
        module = CapaFactory.create(max_attempts='')
        html = module.get_problem_html()
        self.assertTrue(html is not None)
        # assert that we got here without exploding

    def test_get_problem_html(self):
        module = CapaFactory.create()

        # We've tested the show/hide button logic in other tests,
        # so here we hard-wire the values
        show_check_button = bool(random.randint(0, 1) % 2)
        show_reset_button = bool(random.randint(0, 1) % 2)
        show_save_button = bool(random.randint(0, 1) % 2)

        module.should_show_check_button = Mock(return_value=show_check_button)
        module.should_show_reset_button = Mock(return_value=show_reset_button)
        module.should_show_save_button = Mock(return_value=show_save_button)

        # Mock the system rendering function
        module.system.render_template = Mock(return_value="<div>Test Template HTML</div>")

        # Patch the capa problem's HTML rendering
        with patch('capa.capa_problem.LoncapaProblem.get_html') as mock_html:
            mock_html.return_value = "<div>Test Problem HTML</div>"

            # Render the problem HTML
            html = module.get_problem_html(encapsulate=False)

            # Also render the problem encapsulated in a <div>
            html_encapsulated = module.get_problem_html(encapsulate=True)

        # Expect that we get the rendered template back
        self.assertEqual(html, "<div>Test Template HTML</div>")

        # Check the rendering context
        render_args, _ = module.system.render_template.call_args
        self.assertEqual(len(render_args), 2)

        template_name = render_args[0]
        self.assertEqual(template_name, "problem.html")

        context = render_args[1]
        self.assertEqual(context['problem']['html'], "<div>Test Problem HTML</div>")
        self.assertEqual(bool(context['check_button']), show_check_button)
        self.assertEqual(bool(context['reset_button']), show_reset_button)
        self.assertEqual(bool(context['save_button']), show_save_button)

        # Assert that the encapsulated html contains the original html
        self.assertTrue(html in html_encapsulated)

    def test_input_state_consistency(self):
        module1 = CapaFactory.create()
        module2 = CapaFactory.create()

        # check to make sure that the input_state and the keys have the same values
        module1.set_state_from_lcp()
        self.assertEqual(module1.lcp.inputs.keys(), module1.input_state.keys())

        module2.set_state_from_lcp()

        intersection = set(module2.input_state.keys()).intersection(set(module1.input_state.keys()))
        self.assertEqual(len(intersection), 0)

    def test_get_problem_html_error(self):
        """
        In production, when an error occurs with the problem HTML
        rendering, a "dummy" problem is created with an error
        message to display to the user.
        """
        module = CapaFactory.create()

        # Save the original problem so we can compare it later
        original_problem = module.lcp

        # Simulate throwing an exception when the capa problem
        # is asked to render itself as HTML
        module.lcp.get_html = Mock(side_effect=Exception("Test"))

        # Stub out the get_test_system rendering function
        module.system.render_template = Mock(return_value="<div>Test Template HTML</div>")

        # Turn off DEBUG
        module.system.DEBUG = False

        # Try to render the module with DEBUG turned off
        html = module.get_problem_html()

        self.assertTrue(html is not None)

        # Check the rendering context
        render_args, _ = module.system.render_template.call_args
        context = render_args[1]
        self.assertTrue("error" in context['problem']['html'])

        # Expect that the module has created a new dummy problem with the error
        self.assertNotEqual(original_problem, module.lcp)

    def test_get_problem_html_error_w_debug(self):
        """
        Test the html response when an error occurs with DEBUG on
        """
        module = CapaFactory.create()

        # Simulate throwing an exception when the capa problem
        # is asked to render itself as HTML
        error_msg = u"Superterrible error happened: ☠"
        module.lcp.get_html = Mock(side_effect=Exception(error_msg))

        # Stub out the get_test_system rendering function
        module.system.render_template = Mock(return_value="<div>Test Template HTML</div>")

        # Make sure DEBUG is on
        module.system.DEBUG = True

        # Try to render the module with DEBUG turned on
        html = module.get_problem_html()

        self.assertTrue(html is not None)

        # Check the rendering context
        render_args, _ = module.system.render_template.call_args
        context = render_args[1]
        self.assertTrue(error_msg in context['problem']['html'])

    def test_random_seed_no_change(self):

        # Run the test for each possible rerandomize value
        for rerandomize in ['false', 'never',
                            'per_student', 'always',
                            'true', 'onreset']:
            module = CapaFactory.create(rerandomize=rerandomize)

            # Get the seed
            # By this point, the module should have persisted the seed
            seed = module.seed
            self.assertTrue(seed is not None)

            # If we're not rerandomizing, the seed is always set
            # to the same value (1)
            if rerandomize in ['never']:
                self.assertEqual(seed, 1,
                                 msg="Seed should always be 1 when rerandomize='%s'" % rerandomize)

            # Check the problem
            get_request_dict = {CapaFactory.input_key(): '3.14'}
            module.check_problem(get_request_dict)

            # Expect that the seed is the same
            self.assertEqual(seed, module.seed)

            # Save the problem
            module.save_problem(get_request_dict)

            # Expect that the seed is the same
            self.assertEqual(seed, module.seed)

    def test_random_seed_with_reset(self):

        def _reset_and_get_seed(module):
            '''
            Reset the XModule and return the module's seed
            '''

            # Simulate submitting an attempt
            # We need to do this, or reset_problem() will
            # fail with a complaint that we haven't submitted
            # the problem yet.
            module.done = True

            # Reset the problem
            module.reset_problem({})

            # Return the seed
            return module.seed

        def _retry_and_check(num_tries, test_func):
            '''
            Returns True if *test_func* was successful
            (returned True) within *num_tries* attempts

            *test_func* must be a function
            of the form test_func() -> bool
            '''
            success = False
            for i in range(num_tries):
                if test_func() is True:
                    success = True
                    break
            return success

        # Run the test for each possible rerandomize value
        for rerandomize in ['never', 'false', 'per_student',
                            'always', 'true', 'onreset']:
            module = CapaFactory.create(rerandomize=rerandomize)

            # Get the seed
            # By this point, the module should have persisted the seed
            seed = module.seed
            self.assertTrue(seed is not None)

            # We do NOT want the seed to reset if rerandomize
            # is set to 'never' -- it should still be 1
            # The seed also stays the same if we're randomizing
            # 'per_student': the same student should see the same problem
            if rerandomize in ['never', 'false', 'per_student']:
                self.assertEqual(seed, _reset_and_get_seed(module))

            # Otherwise, we expect the seed to change
            # to another valid seed
            else:

                # Since there's a small chance we might get the
                # same seed again, give it 5 chances
                # to generate a different seed
                success = _retry_and_check(5, lambda: _reset_and_get_seed(module) != seed)

                self.assertTrue(module.seed is not None)
                msg = 'Could not get a new seed from reset after 5 tries'
                self.assertTrue(success, msg)

    def test_random_seed_bins(self):
        # Assert that we are limiting the number of possible seeds.

        # Check the conditions that generate random seeds
        for rerandomize in ['always', 'per_student', 'true', 'onreset']:
            # Get a bunch of seeds, they should all be in 0-999.
            for i in range(200):
                module = CapaFactory.create(rerandomize=rerandomize)
                assert 0 <= module.seed < 1000

    @patch('xmodule.capa_base.log')
    @patch('xmodule.capa_base.Progress')
    def test_get_progress_error(self, mock_progress, mock_log):
        """
        Check that an exception given in `Progress` produces a `log.exception` call.
        """
        error_types = [TypeError, ValueError]
        for error_type in error_types:
            mock_progress.side_effect = error_type
            module = CapaFactory.create()
            self.assertIsNone(module.get_progress())
            mock_log.exception.assert_called_once_with('Got bad progress')
            mock_log.reset_mock()

    @patch('xmodule.capa_base.Progress')
    def test_get_progress_no_error_if_weight_zero(self, mock_progress):
        """
        Check that if the weight is 0 get_progress does not try to create a Progress object.
        """
        mock_progress.return_value = True
        module = CapaFactory.create()
        module.weight = 0
        progress = module.get_progress()
        self.assertIsNone(progress)
        self.assertFalse(mock_progress.called)

    @patch('xmodule.capa_base.Progress')
    def test_get_progress_calculate_progress_fraction(self, mock_progress):
        """
        Check that score and total are calculated correctly for the progress fraction.
        """
        module = CapaFactory.create()
        module.weight = 1
        module.get_progress()
        mock_progress.assert_called_with(0, 1)

        other_module = CapaFactory.create(correct=True)
        other_module.weight = 1
        other_module.get_progress()
        mock_progress.assert_called_with(1, 1)

    def test_get_html(self):
        """
        Check that get_html() calls get_progress() with no arguments.
        """
        module = CapaFactory.create()
        module.get_progress = Mock(wraps=module.get_progress)
        module.get_html()
        module.get_progress.assert_called_once_with()

    def test_get_problem(self):
        """
        Check that get_problem() returns the expected dictionary.
        """
        module = CapaFactory.create()
        self.assertEquals(module.get_problem("data"), {'html': module.get_problem_html(encapsulate=False)})

    # Standard question with shuffle="true" used by a few tests
    common_shuffle_xml = textwrap.dedent("""
        <problem>
        <multiplechoiceresponse>
          <choicegroup type="MultipleChoice" shuffle="true">
            <choice correct="false">Apple</choice>
            <choice correct="false">Banana</choice>
            <choice correct="false">Chocolate</choice>
            <choice correct ="true">Donut</choice>
          </choicegroup>
        </multiplechoiceresponse>
        </problem>
    """)

    def test_check_unmask(self):
        """
        Check that shuffle unmasking is plumbed through: when check_problem is called,
        unmasked names should appear in the track_function event_info.
        """
        module = CapaFactory.create(xml=self.common_shuffle_xml)
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            get_request_dict = {CapaFactory.input_key(): 'choice_3'}  # the correct choice
            module.check_problem(get_request_dict)
            mock_call = mock_track_function.mock_calls[0]
            event_info = mock_call[1][1]
            self.assertEqual(event_info['answers'][CapaFactory.answer_key()], 'choice_3')
            # 'permutation' key added to record how problem was shown
            self.assertEquals(event_info['permutation'][CapaFactory.answer_key()],
                              ('shuffle', ['choice_3', 'choice_1', 'choice_2', 'choice_0']))
            self.assertEquals(event_info['success'], 'correct')

    @unittest.skip("masking temporarily disabled")
    def test_save_unmask(self):
        """On problem save, unmasked data should appear on track_function."""
        module = CapaFactory.create(xml=self.common_shuffle_xml)
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            get_request_dict = {CapaFactory.input_key(): 'mask_0'}
            module.save_problem(get_request_dict)
            mock_call = mock_track_function.mock_calls[0]
            event_info = mock_call[1][1]
            self.assertEquals(event_info['answers'][CapaFactory.answer_key()], 'choice_2')
            self.assertIsNotNone(event_info['permutation'][CapaFactory.answer_key()])

    @unittest.skip("masking temporarily disabled")
    def test_reset_unmask(self):
        """On problem reset, unmask names should appear track_function."""
        module = CapaFactory.create(xml=self.common_shuffle_xml)
        get_request_dict = {CapaFactory.input_key(): 'mask_0'}
        module.check_problem(get_request_dict)
        # On reset, 'old_state' should use unmasked names
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            module.reset_problem(None)
            mock_call = mock_track_function.mock_calls[0]
            event_info = mock_call[1][1]
            self.assertEquals(mock_call[1][0], 'reset_problem')
            self.assertEquals(event_info['old_state']['student_answers'][CapaFactory.answer_key()], 'choice_2')
            self.assertIsNotNone(event_info['permutation'][CapaFactory.answer_key()])

    @unittest.skip("masking temporarily disabled")
    def test_rescore_unmask(self):
        """On problem rescore, unmasked names should appear on track_function."""
        module = CapaFactory.create(xml=self.common_shuffle_xml)
        get_request_dict = {CapaFactory.input_key(): 'mask_0'}
        module.check_problem(get_request_dict)
        # On rescore, state/student_answers should use unmasked names
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            module.rescore_problem()
            mock_call = mock_track_function.mock_calls[0]
            event_info = mock_call[1][1]
            self.assertEquals(mock_call[1][0], 'problem_rescore')
            self.assertEquals(event_info['state']['student_answers'][CapaFactory.answer_key()], 'choice_2')
            self.assertIsNotNone(event_info['permutation'][CapaFactory.answer_key()])

    def test_check_unmask_answerpool(self):
        """Check answer-pool question track_function uses unmasked names"""
        xml = textwrap.dedent("""
            <problem>
            <multiplechoiceresponse>
              <choicegroup type="MultipleChoice" answer-pool="4">
                <choice correct="false">Apple</choice>
                <choice correct="false">Banana</choice>
                <choice correct="false">Chocolate</choice>
                <choice correct ="true">Donut</choice>
              </choicegroup>
            </multiplechoiceresponse>
            </problem>
        """)
        module = CapaFactory.create(xml=xml)
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            get_request_dict = {CapaFactory.input_key(): 'choice_2'}  # mask_X form when masking enabled
            module.check_problem(get_request_dict)
            mock_call = mock_track_function.mock_calls[0]
            event_info = mock_call[1][1]
            self.assertEqual(event_info['answers'][CapaFactory.answer_key()], 'choice_2')
            # 'permutation' key added to record how problem was shown
            self.assertEquals(event_info['permutation'][CapaFactory.answer_key()],
                              ('answerpool', ['choice_1', 'choice_3', 'choice_2', 'choice_0']))
            self.assertEquals(event_info['success'], 'incorrect')


class ComplexEncoderTest(unittest.TestCase):
    def test_default(self):
        """
        Check that complex numbers can be encoded into JSON.
        """
        complex_num = 1 - 1j
        expected_str = '1-1*j'
        json_str = json.dumps(complex_num, cls=ComplexEncoder)
        self.assertEqual(expected_str, json_str[1:-1])  # ignore quotes


class TestProblemCheckTracking(unittest.TestCase):
    """
    Ensure correct tracking information is included in events emitted during problem checks.
    """

    def setUp(self):
        self.maxDiff = None

    def test_choice_answer_text(self):
        factory = self.capa_factory_for_problem_xml("""\
            <problem display_name="Multiple Choice Questions">
              <p>What color is the open ocean on a sunny day?</p>
              <optionresponse>
                <optioninput options="('yellow','blue','green')" correct="blue" label="What color is the open ocean on a sunny day?"/>
              </optionresponse>
              <p>Which piece of furniture is built for sitting?</p>
              <multiplechoiceresponse>
                <choicegroup type="MultipleChoice">
                  <choice correct="false">
                    <text>a table</text>
                  </choice>
                  <choice correct="false">
                    <text>a desk</text>
                  </choice>
                  <choice correct="true">
                    <text>a chair</text>
                  </choice>
                  <choice correct="false">
                    <text>a bookshelf</text>
                  </choice>
                </choicegroup>
              </multiplechoiceresponse>
              <p>Which of the following are musical instruments?</p>
              <choiceresponse>
                <checkboxgroup direction="vertical" label="Which of the following are musical instruments?">
                  <choice correct="true">a piano</choice>
                  <choice correct="false">a tree</choice>
                  <choice correct="true">a guitar</choice>
                  <choice correct="false">a window</choice>
                </checkboxgroup>
              </choiceresponse>
            </problem>
            """)
        module = factory.create()

        answer_input_dict = {
            factory.input_key(2): 'blue',
            factory.input_key(3): 'choice_0',
            factory.input_key(4): ['choice_0', 'choice_1'],
        }

        event = self.get_event_for_answers(module, answer_input_dict)

        self.assertEquals(event['submission'], {
            factory.answer_key(2): {
                'question': 'What color is the open ocean on a sunny day?',
                'answer': 'blue',
                'response_type': 'optionresponse',
                'input_type': 'optioninput',
                'correct': True,
                'variant': '',
            },
            factory.answer_key(3): {
                'question': '',
                'answer': u'<text>a table</text>',
                'response_type': 'multiplechoiceresponse',
                'input_type': 'choicegroup',
                'correct': False,
                'variant': '',
            },
            factory.answer_key(4): {
                'question': 'Which of the following are musical instruments?',
                'answer': [u'a piano', u'a tree'],
                'response_type': 'choiceresponse',
                'input_type': 'checkboxgroup',
                'correct': False,
                'variant': '',
            },
        })

    def capa_factory_for_problem_xml(self, xml):
        class CustomCapaFactory(CapaFactory):
            """
            A factory for creating a Capa problem with arbitrary xml.
            """
            sample_problem_xml = textwrap.dedent(xml)

        return CustomCapaFactory

    def get_event_for_answers(self, module, answer_input_dict):
        with patch.object(module.runtime, 'track_function') as mock_track_function:
            module.check_problem(answer_input_dict)

            self.assertEquals(len(mock_track_function.mock_calls), 1)
            mock_call = mock_track_function.mock_calls[0]
            event = mock_call[1][1]

            return event

    def test_numerical_textline(self):
        factory = CapaFactory
        module = factory.create()

        answer_input_dict = {
            factory.input_key(2): '3.14'
        }

        event = self.get_event_for_answers(module, answer_input_dict)
        self.assertEquals(event['submission'], {
            factory.answer_key(2): {
                'question': '',
                'answer': '3.14',
                'response_type': 'numericalresponse',
                'input_type': 'textline',
                'correct': True,
                'variant': '',
            }
        })

    def test_multiple_inputs(self):
        factory = self.capa_factory_for_problem_xml("""\
            <problem display_name="Multiple Inputs">
              <p>Choose the correct color</p>
              <optionresponse>
                <p>What color is the sky?</p>
                <optioninput options="('yellow','blue','green')" correct="blue"/>
                <p>What color are pine needles?</p>
                <optioninput options="('yellow','blue','green')" correct="green"/>
              </optionresponse>
            </problem>
            """)
        module = factory.create()

        answer_input_dict = {
            factory.input_key(2, 1): 'blue',
            factory.input_key(2, 2): 'yellow',
        }

        event = self.get_event_for_answers(module, answer_input_dict)
        self.assertEquals(event['submission'], {
            factory.answer_key(2, 1): {
                'question': '',
                'answer': 'blue',
                'response_type': 'optionresponse',
                'input_type': 'optioninput',
                'correct': True,
                'variant': '',
            },
            factory.answer_key(2, 2): {
                'question': '',
                'answer': 'yellow',
                'response_type': 'optionresponse',
                'input_type': 'optioninput',
                'correct': False,
                'variant': '',
            },
        })

    def test_rerandomized_inputs(self):
        factory = CapaFactory
        module = factory.create(rerandomize='always')

        answer_input_dict = {
            factory.input_key(2): '3.14'
        }

        event = self.get_event_for_answers(module, answer_input_dict)
        self.assertEquals(event['submission'], {
            factory.answer_key(2): {
                'question': '',
                'answer': '3.14',
                'response_type': 'numericalresponse',
                'input_type': 'textline',
                'correct': True,
                'variant': module.seed,
            }
        })

    def test_file_inputs(self):
        fnames = ["prog1.py", "prog2.py", "prog3.py"]
        fpaths = [os.path.join(DATA_DIR, "capa", fname) for fname in fnames]
        fileobjs = [open(fpath) for fpath in fpaths]
        for fileobj in fileobjs:
            self.addCleanup(fileobj.close)

        factory = CapaFactoryWithFiles
        module = factory.create()

        # Mock the XQueueInterface.
        xqueue_interface = XQueueInterface("http://example.com/xqueue", Mock())
        xqueue_interface._http_post = Mock(return_value=(0, "ok"))  # pylint: disable=protected-access
        module.system.xqueue['interface'] = xqueue_interface

        answer_input_dict = {
            CapaFactoryWithFiles.input_key(response_num=2): fileobjs,
            CapaFactoryWithFiles.input_key(response_num=3): 'None',
        }

        event = self.get_event_for_answers(module, answer_input_dict)
        self.assertEquals(event['submission'], {
            factory.answer_key(2): {
                'question': '',
                'answer': fpaths,
                'response_type': 'coderesponse',
                'input_type': 'filesubmission',
                'correct': False,
                'variant': '',
            },
            factory.answer_key(3): {
                'answer': 'None',
                'correct': True,
                'question': '',
                'response_type': 'customresponse',
                'input_type': 'textline',
                'variant': ''
            }
        })
