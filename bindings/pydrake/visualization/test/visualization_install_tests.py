from os.path import join
import sys
import unittest

import install_test_helper


class TestVisualizationInstalled(unittest.TestCase):

    # TODO(#21023) This test is a bit too tricky in CI.
    # @unittest.skipIf(sys.platform == "darwin", "Skipped for tricky macOS CI")
    def test_meldis_help(self):
        print(f"DEBUG: in file visualizaton_install_tests.py")
        """Ensures we can call `./bin/meldis --help` from install."""
        # Get install directory.
        install_dir = install_test_helper.get_install_dir()
        print(f"DEBUG: install_dir = {install_dir}")
        # N.B. Do not update PYTHONPATH, as the script should handle that
        # itself.
        bin_path = join(install_dir, "bin", "meldis")
        print(f"DEBUG: bin_path = {bin_path}")

        text = install_test_helper.check_output([bin_path, "--help"])
        print(f"DEBUG: text = {text}")
        
        self.assertIn("usage: meldis ", text)

    # # TODO(#21023) This test is a bit too tricky in CI.
    # @unittest.skipIf(sys.platform == "darwin", "Skipped for tricky macOS CI")
    # def test_model_visualizer_help(self):
    #     """Ensures we can call `./bin/model_visualizer --help` from install."""
    #     # Get install directory.
    #     install_dir = install_test_helper.get_install_dir()
    #     # N.B. Do not update PYTHONPATH, as the script should handle that
    #     # itself.
    #     bin_path = join(install_dir, "bin", "model_visualizer")
    #     text = install_test_helper.check_output([bin_path, "--help"])
    #     self.assertIn("usage: model_visualizer ", text)

    # # TODO(#21023) This test is a bit too tricky in CI.
    # @unittest.skipIf(sys.platform == "darwin", "Skipped for tricky macOS CI")
    # def test_drake_models_meshes(self):
    #     """Ensures that the package://drake_models/... can be found by testing
    #     a model that uses a meshfile from that location.
    #     """
    #     install_dir = install_test_helper.get_install_dir()
    #     install_test_helper.check_call([
    #         join(install_dir, "bin", "model_visualizer"),
    #         "--loop_once",
    #         "package://drake_models/"
    #         "ycb/meshes/004_sugar_box_textured.obj"
    #     ])


if __name__ == '__main__':
    print("Testing visualization_install_tests.py AAAAAAA")
    unittest.main()
