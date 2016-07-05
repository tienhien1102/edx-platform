define([
        'js/programs/models/pagination_model',
        'js/programs/routers/core_app_program_router',
        'js/programs/views/program_list_view'
    ],
    function( ProgramsListModel, AdminAppRouter, ProgramListView ) {
        'use strict';

        return AdminAppRouter.extend({
            routes: {
                '': 'programList',
                'new': 'programCreator',
                ':id': 'programDetails'
            },

            loadProgramList: function() {
                if ( !this.programListView ) {
                    this.programListView = new ProgramListView({
                        model: this.programsList
                    });
                }
            },

            programList: function() {
                this.programsList = new ProgramsListModel();
                this.programsList.once( 'sync', this.loadProgramList, this );
                this.programsList.getList();

            }
        });
    }
);
